# Changelog

## [0.1.1](https://github.com/cacack/mcp-server-brewfather/compare/v0.1.0...v0.1.1) (2026-09-29)


### Bug Fixes

* report the package version in the MCP server info ([1e4d882](https://github.com/cacack/mcp-server-brewfather/commit/1e4d8821ace91e693934ff16f0c98d8b38f6e837))

## 0.1.0 (2026-09-28)


### Features

* add create_recipe tool ([25eb043](https://github.com/cacack/mcp-server-brewfather/commit/25eb043f07651a2195c688d8d0b449f5e6fe7feb))
* add update_recipe tool for editing recipe settings and ingredients ([0241cdf](https://github.com/cacack/mcp-server-brewfather/commit/0241cdf73147b09a7e028f643ee95701820c5f9f))
* fetch only the latest reading when get_readings limit is 1 ([10d3361](https://github.com/cacack/mcp-server-brewfather/commit/10d33610e1f7e52a6015475dcb0c1e7ff87a1c26)), closes [#10](https://github.com/cacack/mcp-server-brewfather/issues/10)
* migrate to mcp 2 MCPServer ([77dd155](https://github.com/cacack/mcp-server-brewfather/commit/77dd1559f7326a1e8789906f2d459db7fcb0096c))
* scaffold Brewfather MCP server ([82b09ed](https://github.com/cacack/mcp-server-brewfather/commit/82b09ed3e4e8b161ea3e9ead97a184477438c5c7))


### Bug Fixes

* harden get_readings limit=1 per panel review ([509a075](https://github.com/cacack/mcp-server-brewfather/commit/509a075fbb965602f4d8edbb3a0c5f5611628564)), closes [#10](https://github.com/cacack/mcp-server-brewfather/issues/10)
* project batch estimates and drop boolean measured flags ([c0a1e28](https://github.com/cacack/mcp-server-brewfather/commit/c0a1e2816078ef5e338c54d3a955d5471741d554))
