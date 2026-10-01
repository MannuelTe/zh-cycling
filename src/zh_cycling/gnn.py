"""Inductive edge-aware spatio-temporal GNN (IGNNK-inspired), plain PyTorch.

* shared weights, no site-ID embeddings -> can be applied to unseen nodes
* per-node inputs: masked log1p count, availability flag, device-normalised
  anomaly, broadcast weather/calendar, static network covariates
* layers alternate a temporal convolution (per node, along the window) and
  gated, edge-aware message passing (edge attrs: cycling time, exp(-t/tau))
* trained by hiding random sets of observed sensors within each window and
  scoring only their withheld valid labels (MAE on log1p)

Message passing is written with index_add_ instead of PyTorch Geometric: the
graphs are tiny (<= ~120 nodes), and this keeps the install to plain torch,
which runs on CPU or Apple-silicon MPS.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn

from . import config as C
from .graph import knn_edges
from .panel import Panel

L_WIN = 48  # hours per window: 24 h context + 24 h predicted
TAU_S = 300.0


@dataclass
class GNNConfig:
    graph: str = "sensor"  # "sensor" | "intersection"
    hidden: int = 48
    layers: int = 3
    k: int = 5
    lr: float = 2e-3
    batch: int = 16
    max_epochs: int = 40
    patience: int = 6
    hide_min: float = 0.15
    hide_max: float = 0.5
    device: str = "cpu"


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------
def _mlp(i, o, h=None):
    h = h or o
    return nn.Sequential(nn.Linear(i, h), nn.GELU(), nn.Linear(h, o))


class Layer(nn.Module):
    def __init__(self, d: int, e: int):
        super().__init__()
        self.tconv = nn.Conv1d(d, d, kernel_size=5, padding=2)
        self.n1 = nn.LayerNorm(d)
        self.msg = _mlp(2 * d + e, d)
        self.gate = nn.Linear(2 * d + e, 1)
        self.upd = _mlp(2 * d, d)
        self.n2 = nn.LayerNorm(d)

    def forward(self, h, src, dst, eattr):
        B, L, N, d = h.shape
        z = h.permute(0, 2, 3, 1).reshape(B * N, d, L)
        z = self.tconv(z).reshape(B, N, d, L).permute(0, 3, 1, 2)
        h = self.n1(h + nn.functional.gelu(z))
        ea = eattr[None, None].expand(B, L, -1, -1)
        inp = torch.cat([h[:, :, src], h[:, :, dst], ea], -1)
        a = torch.sigmoid(self.gate(inp)) * eattr[:, 1:2]  # learned gate x distance decay
        m = self.msg(inp) * a
        agg = torch.zeros_like(h).index_add_(2, dst, m)
        den = torch.zeros(B, L, N, 1, device=h.device).index_add_(2, dst, a)
        agg = agg / (den + 1e-6)
        return self.n2(h + self.upd(torch.cat([h, agg], -1)))


class SpatioTemporalGNN(nn.Module):
    def __init__(self, n_dyn: int, n_glob: int, n_static: int, d: int, layers: int, n_edge: int = 2):
        super().__init__()
        self.inp = _mlp(n_dyn + n_glob + n_static, d)
        self.layers = nn.ModuleList([Layer(d, n_edge) for _ in range(layers)])
        self.out = _mlp(d, 1, d)

    def forward(self, dyn, glob, static, src, dst, eattr):
        B, L, N, _ = dyn.shape
        x = torch.cat([dyn, glob[:, :, None].expand(B, L, N, -1), static[None, None].expand(B, L, N, -1)], -1)
        h = self.inp(x)
        for layer in self.layers:
            h = layer(h, src, dst, eattr)
        return self.out(h).squeeze(-1)  # predicted log1p count


# --------------------------------------------------------------------------
# graph for a given node subset
# --------------------------------------------------------------------------
class GraphView:
    """Node subset + edges for one fold. `keep` indexes p.nodes."""

    def __init__(self, p: Panel, cfg: GNNConfig, drop_sites: set[str]):
        is_sensor = (p.nodes.node_type == "sensor").to_numpy()
        keep = ~(p.nodes.node_id.isin(drop_sites).to_numpy())
        if cfg.graph == "sensor":
            keep &= is_sensor
        self.idx = np.where(keep)[0]  # into p.nodes
        self.sensor_pos = {p.nodes.node_id[i]: j for j, i in enumerate(self.idx) if is_sensor[i]}
        T = p.T[np.ix_(self.idx, self.idx)]
        if cfg.graph == "sensor":
            src, dst, ea = knn_edges(T, cfg.k, TAU_S)
        else:
            src, dst, ea = _contracted_edges(p, self.idx, drop_sites)
        self.src, self.dst, self.eattr = src, dst, ea.astype(np.float32)
        # map panel site columns -> view positions
        self.site_cols = np.array([p.sites.index(n) for n in self.sensor_pos])
        self.site_pos = np.array(list(self.sensor_pos.values()))

    @property
    def N(self):
        return len(self.idx)


def _contracted_edges(p: Panel, idx: np.ndarray, drop: set[str]):
    e = pd.read_parquet(C.PROCESSED / f"edges_intersection{C.COST_SUFFIX}.parquet", columns=["src", "dst", "cost_s"])
    best: dict[tuple[str, str], float] = {}
    for s, d, t in e.itertuples(index=False):
        best[(s, d)] = min(t, best.get((s, d), np.inf))
    # bypass removed nodes so the remaining network stays connected through them
    for r in drop:
        ins = [(a, t) for (a, b), t in best.items() if b == r]
        outs = [(b, t) for (a, b), t in best.items() if a == r]
        for a, ta in ins:
            for b, tb in outs:
                if a != b:
                    best[(a, b)] = min(ta + tb, best.get((a, b), np.inf))
        best = {k: v for k, v in best.items() if r not in k}
    pos = {p.nodes.node_id[i]: j for j, i in enumerate(idx)}
    pairs = [(pos[a], pos[b], t) for (a, b), t in best.items() if a in pos and b in pos]
    s, d, t = map(np.array, zip(*pairs))
    return s, d, np.c_[t / 60.0, np.exp(-t / TAU_S)]


# --------------------------------------------------------------------------
# data windows
# --------------------------------------------------------------------------
def window_starts(p: Panel, start: str, end: str) -> np.ndarray:
    """Start rows of 48 h windows whose second day lies in [start, end)."""
    days = pd.date_range(start, end, freq="D", inclusive="left")
    s = p.hours.get_indexer(days - pd.Timedelta(hours=24))
    return s[(s >= 0) & (s + L_WIN <= len(p.hours))]


class Batcher:
    def __init__(self, p: Panel, view: GraphView, device):
        self.p, self.v, self.dev = p, view, device
        N = view.N
        H = len(p.hours)
        L = np.zeros((H, N), np.float32)
        Mk = np.zeros((H, N), bool)
        An = np.zeros((H, N), np.float32)
        L[:, view.site_pos] = np.nan_to_num(np.log1p(p.Y[:, view.site_cols]))
        Mk[:, view.site_pos] = p.M[:, view.site_cols]
        An[:, view.site_pos] = np.nan_to_num(np.log1p(p.Y[:, view.site_cols]) - p.devmean[:, view.site_cols])
        self.L, self.M, self.A = L, Mk, An
        self.static = torch.tensor(p.static[view.idx], device=device)
        self.glob = p.glob
        self.src = torch.tensor(view.src, device=device)
        self.dst = torch.tensor(view.dst, device=device)
        self.eattr = torch.tensor(view.eattr, device=device)

    def make(self, starts: np.ndarray, hidden: np.ndarray, loss_nodes: np.ndarray | None = None):
        """hidden: (B, N) bool nodes whose inputs are removed.
        loss_nodes: (B, N) bool nodes scored (default = hidden)."""
        rows = starts[:, None] + np.arange(L_WIN)[None]
        Lw, Mw, Aw = self.L[rows], self.M[rows], self.A[rows]  # (B, L, N)
        vis = Mw & ~hidden[:, None, :]
        dyn = np.stack([Lw * vis, vis.astype(np.float32), Aw * vis], -1)
        ln = hidden if loss_nodes is None else loss_nodes
        lmask = Mw & ln[:, None, :]
        lmask[:, :24] = False  # score only the second day (first day = context)
        t = lambda a: torch.tensor(a, device=self.dev)
        return t(dyn), t(self.glob[rows]), t(Lw), t(lmask)


# --------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------
def _eval_loss(model, bat: Batcher, starts, hide, batch):
    model.eval()
    tot, n = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(starts), batch):
            s = starts[i : i + batch]
            h = np.repeat(hide[None], len(s), 0)
            dyn, glob, y, lm = bat.make(s, h)
            if lm.sum() == 0:
                continue
            pred = model(dyn, glob, bat.static, bat.src, bat.dst, bat.eattr)
            tot += (pred - y).abs()[lm].sum().item()
            n += lm.sum().item()
    return tot / max(n, 1)


def train(p: Panel, cfg: GNNConfig, drop_sites: set[str], train_sites: list[str], val_sites: list[str],
          fixed_epochs: int | None = None, seed: int = C.SEED, verbose: bool = True):
    """Train on windows in the training period. Nodes in `drop_sites` are not
    in the graph. `val_sites` are in the graph but always hidden and never
    scored during training; their 2024 loss drives early stopping."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    view = GraphView(p, cfg, drop_sites)
    bat = Batcher(p, view, cfg.device)
    model = SpatioTemporalGNN(3, p.glob.shape[1], p.static.shape[1], cfg.hidden, cfg.layers).to(cfg.device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=1e-4)
    tr_starts = window_starts(p, C.PANEL_START, C.TRAIN_END)
    va_starts = window_starts(p, C.TRAIN_END, C.VAL_END)
    train_pos = np.array([view.sensor_pos[s] for s in train_sites if s in view.sensor_pos])
    val_pos = np.array([view.sensor_pos[s] for s in val_sites if s in view.sensor_pos], dtype=int)
    always_hidden = np.ones(view.N, bool)
    always_hidden[train_pos] = False  # junctions + val sites stay hidden
    val_hide = always_hidden.copy()

    best, best_ep, bad, hist = np.inf, 0, 0, []
    best_state = None
    epochs = fixed_epochs or cfg.max_epochs
    for ep in range(1, epochs + 1):
        model.train()
        t0 = time.time()
        perm = rng.permutation(tr_starts)
        tl, tn = 0.0, 0
        for i in range(0, len(perm), cfg.batch):
            s = perm[i : i + cfg.batch]
            hid = np.repeat(always_hidden[None], len(s), 0)
            loss_nodes = np.zeros_like(hid)
            for b in range(len(s)):
                r = rng.uniform(cfg.hide_min, cfg.hide_max)
                pick = train_pos[rng.random(len(train_pos)) < r]
                if len(pick) == 0:
                    pick = rng.choice(train_pos, 1)
                hid[b, pick] = True
                loss_nodes[b, pick] = True
            dyn, glob, y, lm = bat.make(s, hid, loss_nodes)
            if lm.sum() == 0:
                continue
            pred = model(dyn, glob, bat.static, bat.src, bat.dst, bat.eattr)
            loss = (pred - y).abs()[lm].mean()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tl += loss.item() * lm.sum().item()
            tn += lm.sum().item()
        msg = f"    ep {ep:02d} train {tl / max(tn, 1):.4f}"
        if fixed_epochs is None and len(val_pos):
            vl = _eval_loss(model, bat, va_starts, val_hide, 32)
            hist.append(vl)
            msg += f" val {vl:.4f}"
            if vl < best - 1e-4:
                best, best_ep, bad, best_state = vl, ep, 0, copy.deepcopy(model.state_dict())
            else:
                bad += 1
        if verbose:
            print(msg + f" ({time.time() - t0:.1f}s)", flush=True)
        if fixed_epochs is None and bad >= cfg.patience:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, view, {"best_epoch": best_ep or epochs, "best_val": best, "val_hist": hist}


def predict(model, p: Panel, cfg: GNNConfig, view: GraphView, query_sites: list[str], start: str, end: str,
            extra_hidden: list[str] = ()) -> pd.DataFrame:
    """Predict hourly counts for `query_sites` over [start, end). The query
    nodes (and `extra_hidden`) have their inputs removed. Query sites that were
    dropped during training are inserted into the graph here."""
    drop = set(p.sites) - set(view.sensor_pos) - set(query_sites) - set(extra_hidden)
    v = GraphView(p, cfg, drop)
    bat = Batcher(p, v, cfg.device)
    hide = np.zeros(v.N, bool)
    hide[[i for i, n in enumerate(p.nodes.node_id[v.idx]) if n not in v.sensor_pos]] = True
    for s in list(query_sites) + list(extra_hidden):
        hide[v.sensor_pos[s]] = True
    starts = window_starts(p, start, end)
    qpos = [v.sensor_pos[s] for s in query_sites]
    out = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(starts), 32):
            s = starts[i : i + 32]
            dyn, glob, _, _ = bat.make(s, np.repeat(hide[None], len(s), 0))
            pr = model(dyn, glob, bat.static, bat.src, bat.dst, bat.eattr).cpu().numpy()
            for b, st in enumerate(s):
                rows = st + np.arange(24, L_WIN)
                for q, site in zip(qpos, query_sites):
                    out.append(pd.DataFrame({"row": rows, "site": site, "pred_log": pr[b, 24:, q]}))
    df = pd.concat(out, ignore_index=True)
    df["pred"] = np.expm1(np.clip(df.pred_log, 0, None))
    return df
