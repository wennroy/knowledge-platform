---
tags: [auth, security]
---
# 鉴权设计

使用 Bearer token + JWT。配合 [[api-design]] 与 [[rate-limiting]] 使用。

## Token 生命周期
- Access token: 15 分钟
- Refresh token: 7 天
