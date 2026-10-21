---
tags: [api, architecture, backend]
---
# API 设计原则

团队 API 遵循 [[tech-stack]] 中的 OpenAI 兼容接口规范。详见 [[auth-design]]。

## 鉴权
所有内部 API 使用 Bearer token，参见 [[security-policy]]。

## 限流
按用户 ID 限流，参见 [[rate-limiting]]。
