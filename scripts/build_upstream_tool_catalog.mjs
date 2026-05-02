import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const workspaceRoot = path.resolve(repoRoot, "..", "..");
const serverRoot = path.resolve(workspaceRoot, "unity-mcp-server");
const outputPath = path.resolve(
  repoRoot,
  "cli_anything",
  "unity_mcp",
  "data",
  "upstream_tool_catalog.json"
);

function inferCategory(name) {
  if (name === "unity_advanced_tool" || name === "unity_list_advanced_tools") {
    return "meta";
  }
  if (name === "unity_get_project_context") {
    return "context";
  }
  if (!name.startsWith("unity_")) {
    return "misc";
  }
  const parts = name.replace(/^unity_/, "").split("_");
  return parts[0] || "misc";
}

function stableStringify(value) {
  return JSON.stringify(value, null, 2) + "\n";
}

function buildBridgeRouteMap(bridgeSource) {
  const routeMap = new Map();
  const sendCommandRegex =
    /export\s+async\s+function\s+(\w+)\([^)]*\)\s*{\s*return\s+sendCommand\("([^"]+)"/g;

  for (const match of bridgeSource.matchAll(sendCommandRegex)) {
    routeMap.set(match[1], match[2]);
  }

  routeMap.set("ping", "ping");
  routeMap.set("getQueueInfo", "queue/info");
  routeMap.set("getTicketStatus", "queue/status");
  routeMap.set("getProjectContext", "context");
  return routeMap;
}

function extractBridgeFunctionName(handler) {
  const source = handler.toString();
  const bridgeMatch = source.match(/bridge\.(\w+)\s*\(/);
  if (bridgeMatch) {
    return bridgeMatch[1];
  }

  const localMatch = source.match(
    /\b(discoverInstances|selectInstance|getSelectedInstance|autoSelectInstance)\s*\(/
  );
  if (localMatch) {
    return localMatch[1];
  }

  return null;
}

async function main() {
  const bridgePath = path.resolve(serverRoot, "src", "unity-editor-bridge.js");
  const editorToolsModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tools", "editor-tools.js")).href
  );
  const hubToolsModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tools", "hub-tools.js")).href
  );
  const instanceToolsModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tools", "instance-tools.js")).href
  );
  const contextToolsModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tools", "context-tools.js")).href
  );
  const umaToolsModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tools", "uma-tools.js")).href
  );
  const toolTiersModule = await import(
    pathToFileURL(path.resolve(serverRoot, "src", "tool-tiers.js")).href
  );

  const editorTools = editorToolsModule.editorTools || [];
  const hubTools = hubToolsModule.hubTools || [];
  const instanceTools = instanceToolsModule.instanceTools || [];
  const contextTools = contextToolsModule.contextTools || [];
  const umaTools = umaToolsModule.umaTools || [];
  const { coreTools, metaTools } = toolTiersModule.splitToolTiers([
    ...editorTools,
    ...umaTools,
  ]);

  const bridgeSource = await fs.readFile(bridgePath, "utf8");
  const routeMap = buildBridgeRouteMap(bridgeSource);

  const coreNames = new Set(coreTools.map((tool) => tool.name));
  const advancedNames = new Set(
    [...editorTools, ...umaTools]
      .map((tool) => tool.name)
      .filter((name) => !coreNames.has(name))
  );
  const metaNames = new Set(metaTools.map((tool) => tool.name));
  const instanceNames = new Set(instanceTools.map((tool) => tool.name));
  const hubNames = new Set(hubTools.map((tool) => tool.name));
  const contextNames = new Set(contextTools.map((tool) => tool.name));

  const allTools = [
    ...instanceTools,
    ...hubTools,
    ...coreTools,
    ...metaTools,
    ...contextTools,
    ...[...editorTools, ...umaTools].filter((tool) => advancedNames.has(tool.name)),
  ];

  const catalog = allTools
    .map((tool) => {
      const bridgeFunction = extractBridgeFunctionName(tool.handler);
      const route = bridgeFunction ? routeMap.get(bridgeFunction) || null : null;

      let tier = "advanced";
      if (metaNames.has(tool.name)) {
        tier = "meta";
      } else if (instanceNames.has(tool.name)) {
        tier = "instance";
      } else if (hubNames.has(tool.name)) {
        tier = "hub";
      } else if (contextNames.has(tool.name)) {
        tier = "context";
      } else if (coreNames.has(tool.name)) {
        tier = "core";
      } else if (advancedNames.has(tool.name)) {
        tier = "advanced";
      }

      const special =
        tier === "meta" ||
        tier === "instance" ||
        tier === "hub" ||
        bridgeFunction === "getQueueInfo" ||
        bridgeFunction === "getTicketStatus";

      return {
        name: tool.name,
        description: tool.description || "",
        category: inferCategory(tool.name),
        tier,
        route,
        execution: special ? "special" : "route",
        unsupported: tool.name.startsWith("unity_hub_"),
        bridgeFunction,
        inputSchema: tool.inputSchema || { type: "object", properties: {} },
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name));

  const payload = {
    generatedAt: new Date().toISOString(),
    source: "upstream-unity-mcp-server",
    totalTools: catalog.length,
    tools: catalog,
  };

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, stableStringify(payload), "utf8");
  console.log(`Wrote ${catalog.length} tool records to ${outputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
