"""LLM cost logging and reporting."""
import config
from pipeline import db


def compute_cost(model: str, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0, batch: bool = False) -> float:
    p = config.PRICES.get(model)
    if p is None:
        print(f"WARNING: no price configured for {model}; logging cost as 0")
        return 0.0
    usd = (input_tokens * p["input"] + output_tokens * p["output"]
           + cache_read_tokens * p["cache_read"] + cache_write_tokens * p["cache_write"]) / 1_000_000
    return usd * (config.BATCH_DISCOUNT if batch else 1.0)


def log_usage(conn, purpose: str, model: str, usage, batch: bool = False) -> float:
    """Record one call's token usage (a pipeline.llm.Usage) in llm_calls and return its cost."""
    inp, out = usage.input_tokens, usage.output_tokens
    cr, cw = usage.cache_read_tokens, usage.cache_write_tokens
    cost = compute_cost(model, inp, out, cr, cw, batch)
    conn.execute(
        """INSERT INTO llm_calls (purpose, model, input_tokens, output_tokens, cache_read_tokens,
                                  cache_write_tokens, batch, cost_usd, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (purpose, model, inp, out, cr, cw, int(batch), cost, db.now()),
    )
    conn.commit()
    return cost


def run() -> None:
    conn = db.connect()
    rows = conn.execute(
        """SELECT purpose, model, COUNT(*) n, SUM(input_tokens) i, SUM(output_tokens) o,
                  SUM(cache_read_tokens) cr, SUM(cache_write_tokens) cw, SUM(cost_usd) usd
           FROM llm_calls GROUP BY purpose, model ORDER BY usd DESC"""
    ).fetchall()
    if not rows:
        print("No LLM calls logged yet. Total spend: $0.00")
        return
    print(f"{'purpose':<22} {'model':<28} {'calls':>6} {'in':>10} {'out':>9} {'c.read':>9} {'c.write':>9} {'USD':>9}")
    total = 0.0
    for r in rows:
        total += r["usd"] or 0
        print(f"{r['purpose']:<22} {r['model']:<28} {r['n']:>6} {r['i'] or 0:>10} {r['o'] or 0:>9} "
              f"{r['cr'] or 0:>9} {r['cw'] or 0:>9} {r['usd'] or 0:>9.4f}")
    print(f"{'TOTAL':<22} {'':<28} {'':>6} {'':>10} {'':>9} {'':>9} {'':>9} {total:>9.4f}")
