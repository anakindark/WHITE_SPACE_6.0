import { createHash, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import {
  localhostHostValidation,
  localhostOriginValidation,
  toNodeHandler,
} from "@modelcontextprotocol/node";
import * as z from "zod/v4";

const DEFAULTS = Object.freeze({
  HOST: "127.0.0.1",
  PORT: "8787",
  MCP_PATH: "/mcp",
  WS_API_BASE: "http://127.0.0.1:8820",
  WS_HEALTH_PATH: "/health",
  WS_STATE_PATH: "/state",
  WS_QUEUE_PATH: "/queue",
  WS_CAPABILITIES_PATH: "/capabilities",
  WS_PROPOSAL_PATH: "/proposals",
  WS_TIMEOUT_MS: "5000",
  WS_MAX_RESPONSE_BYTES: "1048576",
  WS_ALLOWED_API_HOSTS: "127.0.0.1,localhost,::1,[::1]",
  WS_ENABLE_PROPOSALS: "false",
});

function envValue(env, key) {
  return env[key] ?? DEFAULTS[key] ?? "";
}

function parseBool(value) {
  return String(value).trim().toLowerCase() === "true";
}

function normalizeHost(hostname) {
  return hostname.toLowerCase();
}

function parseAllowedHosts(value) {
  return new Set(
    String(value)
      .split(",")
      .map((v) => normalizeHost(v.trim()))
      .filter(Boolean)
  );
}

function validateApiBase(value, allowedHosts) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("WS_API_BASE must use http or https.");
  }
  if (!allowedHosts.has(normalizeHost(url.hostname))) {
    throw new Error(
      `WS_API_BASE hostname "${url.hostname}" is not in WS_ALLOWED_API_HOSTS.`
    );
  }
  return url;
}

function validatePath(value, name) {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("..") ||
    value.includes("?") ||
    value.includes("#")
  ) {
    throw new Error(`${name} must be a fixed absolute path without '..', query, or fragment.`);
  }
  return value;
}

export function buildBridgeConfig(env = process.env) {
  const allowedApiHosts = parseAllowedHosts(envValue(env, "WS_ALLOWED_API_HOSTS"));
  const apiBase = validateApiBase(envValue(env, "WS_API_BASE"), allowedApiHosts);

  const port = Number(envValue(env, "PORT"));
  const timeoutMs = Number(envValue(env, "WS_TIMEOUT_MS"));
  const maxResponseBytes = Number(envValue(env, "WS_MAX_RESPONSE_BYTES"));

  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error("PORT must be an integer from 0 to 65535.");
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 120000) {
    throw new Error("WS_TIMEOUT_MS must be an integer from 100 to 120000.");
  }
  if (
    !Number.isInteger(maxResponseBytes) ||
    maxResponseBytes < 1024 ||
    maxResponseBytes > 10 * 1024 * 1024
  ) {
    throw new Error(
      "WS_MAX_RESPONSE_BYTES must be between 1024 and 10485760 bytes."
    );
  }

  return Object.freeze({
    host: envValue(env, "HOST"),
    port,
    mcpPath: validatePath(envValue(env, "MCP_PATH"), "MCP_PATH"),
    apiBase,
    healthPath: validatePath(envValue(env, "WS_HEALTH_PATH"), "WS_HEALTH_PATH"),
    statePath: validatePath(envValue(env, "WS_STATE_PATH"), "WS_STATE_PATH"),
    queuePath: validatePath(envValue(env, "WS_QUEUE_PATH"), "WS_QUEUE_PATH"),
    capabilitiesPath: validatePath(
      envValue(env, "WS_CAPABILITIES_PATH"),
      "WS_CAPABILITIES_PATH"
    ),
    proposalPath: validatePath(
      envValue(env, "WS_PROPOSAL_PATH"),
      "WS_PROPOSAL_PATH"
    ),
    timeoutMs,
    maxResponseBytes,
    bearerToken: env.WS_BRIDGE_BEARER_TOKEN ?? "",
    proposalsEnabled: parseBool(envValue(env, "WS_ENABLE_PROPOSALS")),
  });
}

function endpoint(config, path) {
  return new URL(path, config.apiBase).toString();
}

async function readBoundedText(response, maxBytes) {
  const text = await response.text();
  const bytes = Buffer.byteLength(text, "utf8");
  if (bytes > maxBytes) {
    throw new Error(
      `WHITE_SPACE API response exceeded ${maxBytes} bytes (${bytes} bytes received).`
    );
  }
  return text;
}

export async function wsRequest(
  config,
  path,
  { method = "GET", body } = {}
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (config.bearerToken) {
    headers.authorization = `Bearer ${config.bearerToken}`;
  }

  try {
    const response = await fetch(endpoint(config, path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      redirect: "error",
    });

    const raw = await readBoundedText(response, config.maxResponseBytes);
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = { raw };
    }

    if (!response.ok) {
      throw new Error(
        `WHITE_SPACE API returned ${response.status}: ${JSON.stringify(data)}`
      );
    }

    return data;
  } finally {
    clearTimeout(timer);
  }
}

function stableValue(value) {
  if (Array.isArray(value)) {
    return value.map(stableValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, stableValue(value[key])])
    );
  }
  return value;
}

export function sha256State(value) {
  return createHash("sha256")
    .update(JSON.stringify(stableValue(value)))
    .digest("hex");
}

function result(message, data) {
  return {
    content: [{ type: "text", text: message }],
    structuredContent: data,
  };
}

export function createWhiteSpaceServer(config) {
  const server = new McpServer(
    {
      name: "white-space-controller",
      version: "0.2.0",
    },
    {
      instructions:
        "WHITE_SPACE is canonical; chat context is not. Read live state before interpreting system state. " +
        "No MCP tool may approve or execute a local action. Human approval remains authoritative.",
    }
  );

  server.registerTool(
    "bridge_contract",
    {
      title: "Read WHITE_SPACE bridge contract",
      description:
        "Returns the fixed authority model for this bridge. This is configuration, not remembered chat state.",
      inputSchema: z.object({}),
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () =>
      result("WHITE_SPACE authority contract loaded.", {
        chat: "non-canonical controller",
        white_space_api: "source of truth",
        pc_runtime: "canonical executor",
        mcp_tools: "contract",
        human_final: "authority",
        direct_execution_available: false,
        proposals_enabled: config.proposalsEnabled,
      })
  );

  server.registerTool(
    "runtime_health",
    {
      title: "Read WHITE_SPACE runtime health",
      description:
        "Reads live runtime health from WHITE_SPACE. Never substitutes chat memory for a failed read.",
      inputSchema: z.object({}),
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(config, config.healthPath);
      return result("Live WHITE_SPACE runtime health read.", { data });
    }
  );

  server.registerTool(
    "system_state",
    {
      title: "Read canonical WHITE_SPACE state",
      description:
        "Reads the current canonical WHITE_SPACE state directly from the configured API and returns a stable SHA-256 observation hash.",
      inputSchema: z.object({}),
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(config, config.statePath);
      return result("Canonical WHITE_SPACE state read.", {
        data,
        state_sha256: sha256State(data),
      });
    }
  );

  server.registerTool(
    "queue_status",
    {
      title: "Read WHITE_SPACE queue status",
      description: "Reads the live WHITE_SPACE queue without changing it.",
      inputSchema: z.object({}),
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(config, config.queuePath);
      return result("Live WHITE_SPACE queue status read.", { data });
    }
  );

  server.registerTool(
    "capabilities",
    {
      title: "Read WHITE_SPACE capabilities",
      description:
        "Reads the current capability surface exposed by WHITE_SPACE. The result is authoritative only for the time of the read.",
      inputSchema: z.object({}),
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: false,
      },
    },
    async () => {
      const data = await wsRequest(config, config.capabilitiesPath);
      return result("Live WHITE_SPACE capabilities read.", { data });
    }
  );

  if (config.proposalsEnabled) {
    server.registerTool(
      "propose_action",
      {
        title: "Create a WHITE_SPACE action proposal",
        description:
          "Creates an unapproved proposal in WHITE_SPACE. It cannot approve or execute the proposal. Human approval remains outside this bridge.",
        inputSchema: z.object({
          action: z.string().min(1).max(120),
          reason: z.string().min(1).max(2000),
          parameters: z.record(z.string(), z.unknown()).optional(),
        }),
        annotations: {
          readOnlyHint: false,
          destructiveHint: false,
          idempotentHint: false,
          openWorldHint: false,
        },
      },
      async ({ action, reason, parameters = {} }) => {
        const currentState = await wsRequest(config, config.statePath);
        const observedStateSha256 = sha256State(currentState);
        const proposalId = randomUUID();

        const proposal = {
          proposal_id: proposalId,
          action,
          reason,
          parameters,
          requested_by: "chatgpt-mcp",
          requires_human_approval: true,
          approved: false,
          execute: false,
          observed_state_sha256: observedStateSha256,
        };

        const response = await wsRequest(config, config.proposalPath, {
          method: "POST",
          body: proposal,
        });

        return result(
          "Proposal created. No action was approved or executed by this bridge.",
          {
            proposal_id: proposalId,
            observed_state_sha256: observedStateSha256,
            requires_human_approval: true,
            executed: false,
            runtime_response: response,
          }
        );
      }
    );
  }

  return server;
}

export async function startBridge({ env = process.env, logger = console } = {}) {
  const config = buildBridgeConfig(env);
  const mcpHandler = createMcpHandler(
    () => createWhiteSpaceServer(config),
    { responseMode: "json" }
  );
  const nodeHandler = toNodeHandler(mcpHandler);
  const validateHost = localhostHostValidation();
  const validateOrigin = localhostOriginValidation();

  const httpServer = createServer((req, res) => {
    if (!validateHost(req, res) || !validateOrigin(req, res)) return;

    if (!req.url) {
      res.writeHead(400).end("Missing URL");
      return;
    }

    const url = new URL(req.url, `http://${req.headers.host ?? "localhost"}`);

    if (req.method === "GET" && url.pathname === "/") {
      res
        .writeHead(200, { "content-type": "application/json" })
        .end(
          JSON.stringify({
            service: "WHITE_SPACE MCP bridge",
            version: "0.2.0",
            mode: "non-canonical-controller",
            mcp: config.mcpPath,
            direct_execution_available: false,
            proposals_enabled: config.proposalsEnabled,
          })
        );
      return;
    }

    if (url.pathname !== config.mcpPath) {
      res.writeHead(404).end("Not Found");
      return;
    }

    void nodeHandler(req, res);
  });

  await new Promise((resolve, reject) => {
    const onError = (error) => {
      httpServer.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      httpServer.off("error", onError);
      resolve();
    };
    httpServer.once("error", onError);
    httpServer.once("listening", onListening);
    httpServer.listen(config.port, config.host);
  });

  const address = httpServer.address();
  const actualPort =
    address && typeof address === "object" ? address.port : config.port;

  logger.error(
    `WHITE_SPACE MCP bridge listening on http://${config.host}:${actualPort}${config.mcpPath}`
  );
  logger.error(
    `WHITE_SPACE API base: ${config.apiBase.origin}; direct execution disabled; proposals=${config.proposalsEnabled}`
  );

  return {
    config,
    port: actualPort,
    httpServer,
    mcpHandler,
    async close() {
      httpServer.closeAllConnections?.();
      await mcpHandler.close();
      await new Promise((resolve) => {
        if (!httpServer.listening) {
          resolve();
          return;
        }
        httpServer.close(() => resolve());
      });
    },
  };
}

const isMain =
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  startBridge().catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error));
    process.exitCode = 1;
  });
}
