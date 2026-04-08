# Attribution Notes

This repository is the CLI/client layer only.

It is MIT-licensed for the code in this repo, but it is designed to work with the upstream AnkleBreaker Unity MCP ecosystem:

- `AnkleBreaker-Studio/unity-mcp-plugin`
- `AnkleBreaker-Studio/unity-mcp-server`

## Why This File Exists

People looking at this repo may assume the upstream plugin and server are plain permissive open source. They are not.

The upstream projects currently use the `AnkleBreaker Open License v1.0`, which includes attribution requirements and resale restrictions.

This repo also includes compatibility-oriented metadata generated from the upstream server tool surface. That does not make the upstream backend part of this repo's MIT license.

## Practical Guidance

For normal use of this CLI:

- keep clear credit to the upstream AnkleBreaker Unity MCP ecosystem
- do not remove or hide upstream copyright and license notices when redistributing their code
- do not assume the upstream plugin or server can be relicensed just because this CLI repo is MIT

If you distribute a product, tool, or service built using the upstream plugin or server, review their current license text directly before release.

## Attribution Wording

The upstream license asks for visible attribution such as:

- `Made with AnkleBreaker MCP`
- `Powered by AnkleBreaker MCP`

Use the current upstream license text as the source of truth if their wording changes later.

## Repo Boundary

This file is not saying your own CLI code must use the upstream license.

It is here to make the repo boundary clear:

- this CLI repo: your separate wrapper/client code
- upstream plugin/server: separate software with their own license terms
