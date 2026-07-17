# 指定发行商 pricing 最终结果

- 来源文件: `pricing_fields_readable_expanded_with_issuer_selected_simplified.md`
- 删除模型ID: gpt-oss-120b, openai/gpt-image-2, sora-2
- 删除行数: 3
- 模型数量: 47
- 1000000 token 单价算法: 当前单位价格 * 1000

| 模型ID | 模型名称 | 发行商名称 | pricing 输入单位 | pricing 输入价(USD) | 输入单价(USD/1000000 token) | pricing 输出单位 | pricing 输出价(USD) | 输出单价(USD/1000000 token) | 价格补充说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-r1 | DeepSeek-R1 | DeepSeek | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00222 | 2.22 |  |
| deepseek-r1-0528 | DeepSeek-R1-0528 | DeepSeek | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00222 | 2.22 |  |
| deepseek-v3 | DeepSeek-V3 | DeepSeek | 1000 token | 0.00028 | 0.28 | 1000 token | 0.00111 | 1.11 |  |
| deepseek-v3-0324 | DeepSeek-V3-0324 | DeepSeek | 1000 token | 0.00028 | 0.28 | 1000 token | 0.00111 | 1.11 |  |
| deepseek-v3.1 | DeepSeek-V3.1 | DeepSeek | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00167 | 1.67 |  |
| deepseek/deepseek-v4-flash | DeepSeek-V4-Flash | DeepSeek | 1000 token | 0.00014 | 0.14 | 1000 token | 0.00028 | 0.28 |  |
| deepseek/deepseek-v4-pro | DeepSeek-V4-Pro | DeepSeek | 1000 token | 0.00167 | 1.67 | 1000 token | 0.00333 | 3.33 |  |
| deepseek/deepseek-v3.1-terminus | DeepSeek/DeepSeek-V3.1-Terminus | DeepSeek | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00167 | 1.67 |  |
| deepseek/deepseek-v3.1-terminus-thinking | DeepSeek/DeepSeek-V3.1-Terminus-Thinking | DeepSeek | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00167 | 1.67 |  |
| deepseek/deepseek-v3.2-exp | DeepSeek/DeepSeek-V3.2-Exp | DeepSeek | 1000 token | 0.00028 | 0.28 | 1000 token | 0.00042 | 0.42 |  |
| deepseek/deepseek-v3.2-exp-thinking | DeepSeek/DeepSeek-V3.2-Exp-Thinking | DeepSeek | 1000 token | 0.00028 | 0.28 | 1000 token | 0.00042 | 0.42 |  |
| deepseek/deepseek-v3.2-251201 | Deepseek/DeepSeek-V3.2 | DeepSeek | 1000 token | 0.00028 | 0.28 | 1000 token | 0.00042 | 0.42 |  |
| claude-4.0-opus | Claude 4.0 Opus | Anthropic | 1000 token | 0.015 | 15 | 1000 token | 0.0756 | 75.6 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.0-sonnet | Claude 4.0 Sonnet | Anthropic | 1000 token | 0.015 | 15 | 1000 token | 0.01512 | 15.12 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.1-opus | Claude 4.1 Opus | Anthropic | 1000 token | 0.015 | 15 | 1000 token | 0.0756 | 75.6 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.5-haiku | Claude 4.5 Haiku | Anthropic | 1000 token | 0.005 | 5 | 1000 token | 0.00504 | 5.04 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.5-opus | Claude 4.5 Opus | Anthropic | 1000 token | 0.005 | 5 | 1000 token | 0.0252 | 25.2 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.5-sonnet | Claude 4.5 Sonnet | Anthropic | 1000 token | 0.003 | 3 | 1000 token | 0.01512 | 15.12 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.6-opus | Claude 4.6 Opus | Anthropic | 1000 token | 0.005 | 5 | 1000 token | 0.0252 | 25.2 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| claude-4.6-sonnet | Claude 4.6 Sonnet | Anthropic | 1000 token | 0.003 | 3 | 1000 token | 0.01512 | 15.12 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| anthropic/claude-4.7-opus | Claude 4.7 Opus | Anthropic | 1000 token | 0.005 | 5 | 1000 token | 0.0252 | 25.2 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| anthropic/claude-4.8-opus | Claude 4.8 Opus | Anthropic | 1000 token | 0.005 | 5 | 1000 token | 0.0252 | 25.2 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| MiniMax-M1 | MiniMax M1 | Minimax | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00222 | 2.22 |  |
| minimax/minimax-m2 | Minimax/Minimax-M2 | Minimax | 1000 token | 0.00029 | 0.29 | 1000 token | 0.00117 | 1.17 |  |
| minimax/minimax-m2.1 | Minimax/Minimax-M2.1 | Minimax | 1000 token | 0.00029 | 0.29 | 1000 token | 0.00117 | 1.17 |  |
| minimax/minimax-m2.5 | Minimax/Minimax-M2.5 | Minimax | 1000 token | 0.00029 | 0.29 | 1000 token | 0.00117 | 1.17 |  |
| minimax/minimax-m2.5-highspeed | Minimax/Minimax-M2.5 Highspeed | Minimax | 1000 token | 0.00058 | 0.58 | 1000 token | 0.00233 | 2.33 |  |
| minimax/minimax-m2.7 | Minimax/Minimax-M2.7 | Minimax | 1000 token | 0.00029 | 0.29 | 1000 token | 0.00117 | 1.17 |  |
| minimax/minimax-m3 | Minimax/Minimax-M3 | Minimax | 未设置单位 | 0.00029 | 0.29 | 1000 token | 0.01167 | 11.67 | 输入价由 token-price-usd-original-price.xlsx:input_token_original_price 补充 |
| openai/gpt-5 | OpenAI/GPT-5 | OpenAI | 1000 token | 0.00126 | 1.26 | 1000 token | 0.01008 | 10.08 |  |
| openai/gpt-5-nano | OpenAI/GPT-5 Nano | OpenAI | 1000 token | 0.0000504 | 0.0504 | 1000 token | 0.0004032 | 0.4032 |  |
| openai/gpt-5.2 | OpenAI/GPT-5.2 | OpenAI | 1000 token | 0.001764 | 1.764 | 1000 token | 0.014112 | 14.112 |  |
| openai/gpt-5-chat | Openai/GPT-5 Chat | OpenAI | 1000 token | 0.00126 | 1.26 | 1000 token | 0.01008 | 10.08 |  |
| openai/gpt-5-mini | Openai/GPT-5 Mini | OpenAI | 1000 token | 0.000252 | 0.252 | 1000 token | 0.002016 | 2.016 |  |
| openai/gpt-5-pro | Openai/GPT-5 Pro | OpenAI | 1000 token | 0.01512 | 15.12 | 1000 token | 0.12096 | 120.96 |  |
| openai/gpt-5.2-chat | Openai/GPT-5.2 Chat | OpenAI | 1000 token | 0.001764 | 1.764 | 1000 token | 0.014112 | 14.112 |  |
| openai/gpt-5.2-codex | Openai/GPT-5.2 Codex | OpenAI | 1000 token | 0.001764 | 1.764 | 1000 token | 0.014112 | 14.112 |  |
| openai/gpt-5.3-codex | Openai/GPT-5.3 Codex | OpenAI | 1000 token | 0.001764 | 1.764 | 1000 token | 0.014112 | 14.112 |  |
| openai/gpt-5.4 | Openai/GPT-5.4 | OpenAI | 1000 token | 0.00252 | 2.52 | 1000 token | 0.01512 | 15.12 |  |
| openai/gpt-5.4-mini | Openai/GPT-5.4 Mini | OpenAI | 1000 token | 0.000756 | 0.756 | 1000 token | 0.004536 | 4.536 |  |
| openai/gpt-5.4-nano | Openai/GPT-5.4 Nano | OpenAI | 1000 token | 0.0002016 | 0.2016 | 1000 token | 0.00126 | 1.26 |  |
| openai/gpt-5.4-pro | Openai/GPT-5.4 Pro | OpenAI | 1000 token | 0.03024 | 30.24 | 1000 token | 0.18144 | 181.44 |  |
| openai/gpt-5.5 | Openai/GPT-5.5 | OpenAI | 1000 token | 0.00504 | 5.04 | 1000 token | 0.03024 | 30.24 |  |
| kimi-k2 | Kimi K2 | Moonshot-Kimi | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00222 | 2.22 |  |
| moonshotai/kimi-k2-thinking | Kimi K2 Thinking | Moonshot-Kimi | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00222 | 2.22 |  |
| moonshotai/kimi-k2.5 | Moonshotai/Kimi-K2.5 | Moonshot-Kimi | 1000 token | 0.00056 | 0.56 | 1000 token | 0.00292 | 2.92 |  |
| moonshotai/kimi-k2.6 | Moonshotai/Kimi-K2.6 | Moonshot-Kimi | 1000 token | 0.0009 | 0.9 | 1000 token | 0.00375 | 3.75 |  |
