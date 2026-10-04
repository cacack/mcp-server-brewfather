# Changelog

## [0.3.0](https://github.com/cacack/mcp-server-brewfather/compare/v0.2.0...v0.3.0) (2026-10-04)


### Features

* create inventory items and edit their details ([c6a5a86](https://github.com/cacack/mcp-server-brewfather/commit/c6a5a861a28e19de88f82b1da185b41ef0e36e68)), closes [#12](https://github.com/cacack/mcp-server-brewfather/issues/12)
* return structured content from single-object tools ([dca20c7](https://github.com/cacack/mcp-server-brewfather/commit/dca20c7871bf7627c0bfcc27c6dc315e55c7c242)), closes [#13](https://github.com/cacack/mcp-server-brewfather/issues/13)


### Bug Fixes

* report a create response without an id as a readable error ([bb5957e](https://github.com/cacack/mcp-server-brewfather/commit/bb5957e53300f79f389938c25f2f34673127c0fa)), closes [#12](https://github.com/cacack/mcp-server-brewfather/issues/12)

## [0.2.0](https://github.com/cacack/mcp-server-brewfather/compare/v0.1.1...v0.2.0) (2026-10-03)


### Features

* add get_brewtracker tool for brew-day progress ([0740485](https://github.com/cacack/mcp-server-brewfather/commit/07404858e4b23cb46ac09f9ec5a3c88c76aaea01)), closes [#11](https://github.com/cacack/mcp-server-brewfather/issues/11)
* return batch notes, log entries and events from get_batch ([8e56fc3](https://github.com/cacack/mcp-server-brewfather/commit/8e56fc3d0177d993056fff750ba1659b7b207b2d)), closes [#24](https://github.com/cacack/mcp-server-brewfather/issues/24)


### Bug Fixes

* reject ids that could leave their request path ([1a500fc](https://github.com/cacack/mcp-server-brewfather/commit/1a500fc4685c95f2366ff81cd9c8ab5eeb08dd77)), closes [#20](https://github.com/cacack/mcp-server-brewfather/issues/20)
* take get_readings limit=1 from the readings list, not readings/last ([abde3e5](https://github.com/cacack/mcp-server-brewfather/commit/abde3e52a8aba352a31bfaa3e77a5ea9568c7119)), closes [#22](https://github.com/cacack/mcp-server-brewfather/issues/22)

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
