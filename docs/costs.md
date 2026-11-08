# Costs (USD)

`tokens.py` writes the USD cost of a run to `.sjck/tokens.json` and `.sjck/token-report.json`, per node, per agent (one transcript) and for the whole run.

## Real vs estimated

- If a transcript contains a `cost-state` event, the run total is the real cost and `estimated` is `false`. It is split across nodes and agents by token-price weight.
- Otherwise the cost is estimated from the token usage of each model and the configured prices, and `estimated` is `true`. The field is always present (run, node, agent).
- The USD path is offline and is O(already aggregated tokens): it never re-parses a transcript. EUR conversion (ECB) is unchanged and applies only to the real-cost path.

## Prices

Defaults: `sjck-graph/config/prices.json`. Override per project in `.sjck/prices.json`, merged by key (the override wins):

```json
{"multipliers": {"cache_read": 0.08},
 "models": {"sonnet": {"input_per_mtok": 3.5},
            "my-model": {"input_per_mtok": 2.0, "multipliers": {"output": 4.0}}}}
```

- `input_per_mtok`: USD per 1M normal input tokens.
- `multipliers`: price of `output`, `cache_read`, `cache_creation` relative to the input price (defaults 5, 0.1, 1.25). A model may carry its own `multipliers`.
- A model name matches the longest key contained in it (`claude-sonnet-4` -> `sonnet`); `default` is the fallback. A model with no matching price makes `cost.complete` false.

## Output

- `tokens.json`: `cost {usd, by_model, source, estimated, complete}`, `by_node[id].cost_usd/estimated`, `by_agent[id] {node, kind, tokens, models, cost_usd, estimated}`. `by_node[id].models[model]` is now `{input, output, cache_read, cache_creation, total}` (it was an integer).
- `token-report.json`: `cost {usd, estimated, by_node, by_agent}`.
