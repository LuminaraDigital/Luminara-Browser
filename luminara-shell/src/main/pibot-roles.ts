import fs from "node:fs";
import path from "node:path";
import type { BotProfile } from "../shared/types";

const COLOR_MAP: Record<string, string> = {
  teal: "#16A095",
  blue: "#2E7CF6",
  violet: "#7C4DFF",
  purple: "#7C4DFF",
  green: "#199473",
  amber: "#C47F17",
  pink: "#C24B89",
  coral: "#D95D48"
};

const CORE_BOTS: BotProfile[] = [
  {
    id: "remy",
    name: "Remy",
    roleTitle: "Researcher",
    description: "Reads pages deeply, compares claims, and cites every source.",
    color: "#16A095",
    isGroup: false,
    systemPrompt:
      "You are Remy, Luminara Browser's calm, rigorous research specialist. Give conclusion first, then crisp sourced evidence referencing the user's open tabs. Separate fact from inference.",
    quickPrompts: [
      "Summarise this page",
      "Fact-check the claims here",
      "Compare open tabs"
    ],
    source: "builtin"
  },
  {
    id: "dana",
    name: "Dana",
    roleTitle: "Data Analyst",
    description: "Extracts numbers, prices, tables, and sharp side-by-side comparisons.",
    color: "#2E7CF6",
    isGroup: false,
    systemPrompt:
      "You are Dana, Luminara Browser's data analyst. Turn web pages into clear structured comparisons, highlight key prices/metrics, call out missing data or caveats, and stay concise.",
    quickPrompts: [
      "Extract key metrics",
      "Compare pricing across tabs",
      "Spot anomalies on this page"
    ],
    source: "builtin"
  },
  {
    id: "pi",
    name: "Pi",
    roleTitle: "Everyday Co-Pilot",
    description: "Helps draft, organise, automate repeatable skills, and steer web tasks.",
    color: "#7C4DFF",
    isGroup: false,
    systemPrompt:
      "You are Pi, Luminara Browser's helpful co-pilot. Be warm, direct, and actionable. Respect human-in-the-loop approvals for any external mutation.",
    quickPrompts: [
      "Explain this simply",
      "Draft a reply from this page",
      "Suggest next steps"
    ],
    source: "builtin"
  },
  {
    id: "research-team",
    name: "Research Team",
    roleTitle: "Multi-Bot Group",
    description: "Remy gathers sources, Dana builds the comparison table, Pi synthesises the verdict.",
    color: "#199473",
    isGroup: true,
    members: ["remy", "dana", "pi"],
    systemPrompt:
      "You coordinate Luminara's Research Team (Remy for sourcing, Dana for quantitative comparison, Pi for clear synthesis). Present a unified verdict followed by each specialist's concise contribution.",
    quickPrompts: [
      "Run parallel research across tabs",
      "Build a decision brief",
      "Compare pros, cons, and pricing"
    ],
    source: "builtin"
  }
];

interface PiBotTeamFile {
  bots?: Array<{
    ref?: string;
    name?: { en?: string };
    description?: { en?: string };
    systemPrompt?: { en?: string };
    avatarColor?: string;
    role?: { id?: string; name?: { en?: string } };
    quickPrompts?: Array<{ en?: string }>;
  }>;
}

export function loadBotProfiles(builtinDir: string): BotProfile[] {
  const byId = new Map<string, BotProfile>();
  for (const bot of CORE_BOTS) {
    byId.set(bot.id, { ...bot, quickPrompts: [...bot.quickPrompts] });
  }

  const rolesDir = path.join(builtinDir, "roles");
  if (!fs.existsSync(rolesDir)) return Array.from(byId.values());

  let entries: fs.Dirent[] = [];
  try {
    entries = fs
      .readdirSync(rolesDir, { withFileTypes: true })
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    return Array.from(byId.values());
  }

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const teamJsonPath = path.join(rolesDir, entry.name, "team.json");
    if (!fs.existsSync(teamJsonPath)) continue;
    try {
      const parsed = JSON.parse(fs.readFileSync(teamJsonPath, "utf8")) as PiBotTeamFile;
      for (const raw of parsed.bots ?? []) {
        const name = raw.name?.en?.trim();
        if (!name) continue;
        const lower = name.toLowerCase();
        if (lower === "remy" || lower === "dana") {
          const existing = byId.get(lower);
          if (existing) {
            if (raw.description?.en) existing.description = raw.description.en;
            if (raw.systemPrompt?.en) existing.systemPrompt = raw.systemPrompt.en;
            const prompts = (raw.quickPrompts ?? [])
              .map((p) => p.en?.trim() ?? "")
              .filter(Boolean);
            if (prompts.length > 0) existing.quickPrompts = prompts;
            existing.source = "pibot";
          }
          continue;
        }
        const id = (raw.ref || raw.role?.id || lower).toLowerCase();
        if (byId.has(id) || byId.size >= 8) continue;
        byId.set(id, {
          id,
          name,
          roleTitle: raw.role?.name?.en?.trim() || "Specialist",
          description: raw.description?.en?.trim() || "PiBot specialist role.",
          color: COLOR_MAP[raw.avatarColor ?? ""] ?? "#199473",
          isGroup: false,
          systemPrompt:
            raw.systemPrompt?.en?.trim() ||
            `You are ${name}, a specialist assistant inside Luminara Browser.`,
          quickPrompts: (raw.quickPrompts ?? [])
            .map((p) => p.en?.trim() ?? "")
            .filter(Boolean)
            .slice(0, 3),
          source: "pibot"
        });
      }
    } catch {
      // Skip malformed role JSON cleanly
    }
  }

  return Array.from(byId.values());
}
