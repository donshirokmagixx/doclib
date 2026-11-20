// 实时力导向微模拟：只服务于“拖动节点 → 邻居联动 → 缓慢回稳”。
// 不负责布局初排（仍由 fCoSE 完成），因此拖动时不会重跑全图布局，也不会 reset 视口。
// 设计目标：小图 60fps；中等图网格近似斥力；大图自动降帧；松手后 alpha 衰减到静止。

const DEFAULTS = {
  repulsion: 16000,      // 斥力系数（dist² 衰减）
  spring: 0.012,         // 边的弹簧强度
  linkDistance: 125,     // 边的自然长度
  centerStrength: 0.001,
  radialStrength: 0.002, // 软半径环，避免所有叶子被弹簧拉成一团
  damping: 0.88,
  alphaDecay: 0.982,
  alphaMin: 0.02,
  minMotion: 0.02,
  maxSpeed: 26,
  minDistance: 18,
  gridThreshold: 260,
  cellSize: 150,
  maxNodes: 2400,
};

const EDGE_WEIGHT = {
  hierarchy: 0.85,
  mount: 1.15,
  manual: 1.35,
  wikilink: 1.08,
  ai: 0.55,
};

function now() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

export class ForceSim {
  constructor(cy, options = {}) {
    this.cy = cy;
    this.opts = { ...DEFAULTS, ...options };
    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.center = { x: 0, y: 0 };
    this.alpha = 0;
    this.dragged = null;
    this.running = false;
    this.raf = 0;
    this.lastTs = 0;
    this.lastMotion = 0;
    this.iterations = 0;
    this.degraded = false;
    this.onSettle = typeof options.onSettle === 'function' ? options.onSettle : null;
    this.onStats = typeof options.onStats === 'function' ? options.onStats : null;
    this._tick = this._tick.bind(this);
    this.rebuild();
  }

  rebuild() {
    const cy = this.cy;
    this.nodes = [];
    this.edges = [];
    this.byId.clear();
    if (!cy || (cy.destroyed && cy.destroyed())) return;
    const allNodes = cy.nodes();
    for (let i = 0; i < allNodes.length; i++) {
      const n = allNodes[i];
      const p = n.position();
      const rec = {
        n, id: n.id(), idx: i, x: Number(p.x) || 0, y: Number(p.y) || 0,
        vx: 0, vy: 0,
      };
      this.nodes.push(rec);
      this.byId.set(rec.id, rec);
    }
    for (const e of cy.edges()) {
      const a = this.byId.get(e.data('source'));
      const b = this.byId.get(e.data('target'));
      if (!a || !b) continue;
      const rel = e.data('rel') || 'hierarchy';
      this.edges.push({
        a, b, rel,
        weight: EDGE_WEIGHT[rel] || 1,
        length: rel === 'mount' ? 96 : rel === 'ai' ? 132 : this.opts.linkDistance,
      });
    }
    let sx = 0, sy = 0;
    for (const r of this.nodes) { sx += r.x; sy += r.y; }
    this.center = this.nodes.length
      ? { x: sx / this.nodes.length, y: sy / this.nodes.length }
      : { x: 0, y: 0 };
    let r2 = 0;
    for (const r of this.nodes) {
      const dx = r.x - this.center.x, dy = r.y - this.center.y;
      r2 += dx * dx + dy * dy;
    }
    this.restRadius = this.nodes.length ? Math.sqrt(r2 / this.nodes.length) : 0;
    this.degraded = this.nodes.length > this.opts.gridThreshold;
    this.frameInterval = this.nodes.length > 1200 ? 50 : this.nodes.length > 600 ? 33 : 15;
    this.frameMaxSpeed = this.nodes.length > 600 ? 11 : this.nodes.length > 300 ? 16 : this.opts.maxSpeed;
    this.alpha = 0;
    this.lastMotion = 0;
    this.iterations = 0;
  }

  isFixed(rec) {
    return rec === this.dragged || rec.n.locked() || !!rec.n.scratch('_pinned');
  }

  syncDragged(node) {
    if (!this.dragged || this.dragged.id !== node.id()) return;
    const p = node.position();
    this.dragged.vx = (Number(p.x) - this.dragged.x) * 0.45;
    this.dragged.vy = (Number(p.y) - this.dragged.y) * 0.45;
    this.dragged.x = Number(p.x) || 0;
    this.dragged.y = Number(p.y) || 0;
    this.alpha = 1;
  }

  beginDrag(node) {
    const rec = this.byId.get(node.id());
    if (!rec) return;
    this.dragged = rec;
    this.syncDragged(node);
    this.alpha = 1;
    this.start();
  }

  updateDrag(node) {
    if (!this.dragged) {
      this.beginDrag(node);
      return;
    }
    this.syncDragged(node);
  }

  endDrag() {
    if (!this.dragged) return;
    this.dragged = null;
    this.alpha = 1;
    this.start();
  }

  start() {
    if (this.running || !this.nodes.length) return;
    if (this.nodes.length > this.opts.maxNodes) {
      this.degraded = true;
      this.stop('too-large');
      return;
    }
    this.running = true;
    this.lastTs = 0;
    this.raf = requestAnimationFrame(this._tick);
  }

  stop(reason = '') {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    const wasRunning = this.running;
    this.running = false;
    this.alpha = 0;
    if (wasRunning && this.onSettle) {
      try { this.onSettle(reason, this.stats()); } catch (e) { console.warn('force settle callback failed', e); }
    }
  }

  destroy() {
    this.stop('destroy');
    this.dragged = null;
    this.nodes = [];
    this.edges = [];
    this.byId.clear();
    this.cy = null;
  }

  stats() {
    return {
      nodes: this.nodes.length,
      edges: this.edges.length,
      cyNodes: this.cy ? this.cy.nodes().length : -1,
      iterations: this.iterations,
      motion: this.lastMotion,
      alpha: this.alpha,
      degraded: this.degraded,
      frameInterval: this.frameInterval,
    };
  }

  _tick(ts) {
    if (!this.running) return;
    if (!this.cy || (this.cy.destroyed && this.cy.destroyed())) { this.stop('destroyed'); return; }
    const t = Number(ts) || now();
    if (!this.lastTs || t - this.lastTs >= this.frameInterval) {
      this.lastTs = t;
      const keepGoing = this.step();
      if (this.onStats) {
        try { this.onStats(this.stats()); } catch {}
      }
      if (!keepGoing) {
        this.stop(this.dragged ? 'paused' : 'settled');
        return;
      }
    }
    if (this.running) this.raf = requestAnimationFrame(this._tick);
  }

  step() {
    const nodes = this.nodes;
    const n = nodes.length;
    if (!n) return false;
    const cfg = this.opts;
    const alpha = this.alpha;

    for (const r of nodes) { r.fx = 0; r.fy = 0; }

    if (n > cfg.gridThreshold) this._repelGrid(alpha);
    else this._repelDirect(alpha);

    // 弹簧边：只对相连节点施加；所有边权重不同，层级/归属更松，人工关联更紧
    for (const e of this.edges) {
      const a = e.a, b = e.b;
      let dx = b.x - a.x, dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1e-6) { dx = (Math.random() - .5); dy = (Math.random() - .5); d2 = 1; }
      const d = Math.sqrt(d2);
      const f = Math.max(-34, Math.min(34, (d - e.length) * cfg.spring * e.weight * alpha));
      const ux = dx / d, uy = dy / d;
      a.fx += ux * f; a.fy += uy * f;
      b.fx -= ux * f; b.fy -= uy * f;
    }

    // 轻盈的向心约束 + 软半径环：用当前图中心，不改变视口；避免整体漂移或被弹簧拉成一团
    for (const r of nodes) {
      r.fx += (this.center.x - r.x) * cfg.centerStrength;
      r.fy += (this.center.y - r.y) * cfg.centerStrength;
      const dx = r.x - this.center.x, dy = r.y - this.center.y;
      const rad = Math.hypot(dx, dy);
      if (rad > 1 && this.restRadius > 0) {
        const pull = (rad - this.restRadius) * cfg.radialStrength;
        r.fx -= (dx / rad) * pull;
        r.fy -= (dy / rad) * pull;
      }
    }

    let motion = 0;
    const cy = this.cy;
    cy.startBatch();
    for (const r of nodes) {
      if (this.isFixed(r)) {
        r.vx = 0; r.vy = 0;
        continue;
      }
      r.vx = (r.vx + r.fx) * cfg.damping;
      r.vy = (r.vy + r.fy) * cfg.damping;
      const speed = Math.hypot(r.vx, r.vy);
      if (speed > this.frameMaxSpeed) {
        const k = this.frameMaxSpeed / speed;
        r.vx *= k; r.vy *= k;
      }
      const nx = r.x + r.vx;
      const ny = r.y + r.vy;
      r.x = nx; r.y = ny;
      motion = Math.max(motion, Math.abs(r.vx) + Math.abs(r.vy));
      r.n.position({ x: nx, y: ny });
    }
    cy.endBatch();

    this.lastMotion = motion;
    this.iterations += 1;
    if (this.dragged) {
      this.alpha = 1;
      return true;
    }
    this.alpha *= cfg.alphaDecay;
    if (this.alpha < cfg.alphaMin || motion < cfg.minMotion) {
      this.alpha = 0;
      return false;
    }
    return true;
  }

  _repelDirect(alpha) {
    const nodes = this.nodes;
    const cfg = this.opts;
    const rep = cfg.repulsion * alpha;
    const minD2 = cfg.minDistance * cfg.minDistance;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < minD2) {
          if (d2 < 1e-4) { dx = (Math.random() - .5) * 2; dy = (Math.random() - .5) * 2; d2 = 4; }
          else { const s = cfg.minDistance / Math.sqrt(d2); dx *= s; dy *= s; d2 = minD2; }
        }
        const d = Math.sqrt(d2);
        const f = rep / d2;
        const ux = dx / d, uy = dy / d;
        a.fx -= ux * f; a.fy -= uy * f;
        b.fx += ux * f; b.fy += uy * f;
      }
    }
  }

  _repelGrid(alpha) {
    const nodes = this.nodes;
    const cfg = this.opts;
    const rep = cfg.repulsion * alpha;
    const cell = cfg.cellSize;
    const grid = new Map();
    const key = (x, y) => `${x},${y}`;
    for (const r of nodes) {
      const cx = Math.round(r.x / cell), cy = Math.round(r.y / cell);
      const k = key(cx, cy);
      let bucket = grid.get(k);
      if (!bucket) { bucket = []; grid.set(k, bucket); }
      bucket.push(r);
    }
    // 只看相邻 3×3 网格，远处斥力截断；O(N) 近似，供大图降级使用
    for (const a of nodes) {
      const ax = Math.round(a.x / cell), ay = Math.round(a.y / cell);
      for (let gx = -1; gx <= 1; gx++) {
        for (let gy = -1; gy <= 1; gy++) {
          const bucket = grid.get(key(ax + gx, ay + gy));
          if (!bucket) continue;
          for (const b of bucket) {
            if (a.idx >= b.idx) continue;
            const dx = b.x - a.x, dy = b.y - a.y;
            const d2 = dx * dx + dy * dy;
            if (d2 > cell * cell * 9 || d2 < 1e-4) continue;
            const d = Math.sqrt(d2);
            const f = rep / Math.max(d2, cfg.minDistance * cfg.minDistance);
            const ux = dx / d, uy = dy / d;
            a.fx -= ux * f; a.fy -= uy * f;
            b.fx += ux * f; b.fy += uy * f;
          }
        }
      }
    }
  }
}

export function forceDefaults() { return { ...DEFAULTS }; }
