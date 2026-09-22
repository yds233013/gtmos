import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FunnelBars } from "@/components/charts/funnel";
import { MiniMarkdown, parseBlocks } from "@/components/insights/mini-markdown";
import { ActionButton } from "@/components/ui/action-button";
import { DemoBadge, GradeBadge } from "@/components/ui/badge";
import { ScoreBar } from "@/components/ui/score-bar";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

afterEach(() => {
  vi.restoreAllMocks();
  refresh.mockReset();
});

describe("badges and meters", () => {
  it("labels grades and demo data", () => {
    render(
      <>
        <GradeBadge grade="A" score={98} />
        <GradeBadge grade={null} />
        <DemoBadge />
      </>,
    );
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("98")).toBeInTheDocument();
    expect(screen.getByText("Unscored")).toBeInTheDocument();
    expect(screen.getByText("DEMO")).toBeInTheDocument();
  });
  it("exposes score bars as accessible meters", () => {
    render(<ScoreBar value={25} max={35} />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "25");
    expect(meter).toHaveAttribute("aria-valuemax", "35");
  });
  it("renders the funnel as a table with conversions", () => {
    render(
      <FunnelBars
        stages={[
          { stage: "prospect", accounts: 2000, conversion_from_previous: null },
          { stage: "contacted", accounts: 750, conversion_from_previous: 0.375 },
        ]}
      />,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("2,000")).toBeInTheDocument();
    expect(screen.getByText("38%")).toBeInTheDocument();
  });
});

describe("mini markdown", () => {
  it("parses bullets, numbers and paragraphs", () => {
    const blocks = parseBlocks("Intro\n- one\n- two\n1. first\n2. second");
    expect(blocks.map((b) => b.kind)).toEqual(["p", "ul", "ol"]);
  });
  it("never renders raw HTML from answers", () => {
    const { container } = render(<MiniMarkdown source={'**Bold** <img src=x onerror="alert(1)">'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("Bold");
    expect(container.textContent).toContain("<img");
  });
});

describe("ActionButton", () => {
  it("requires a second click when confirmLabel is set, then calls the API and refreshes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    render(
      <ActionButton path="/workflows/x" method="PATCH" body={{ is_enabled: false }} confirmLabel="Confirm disable">
        Disable
      </ActionButton>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Disable" }));
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirm disable" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/workflows/x", expect.objectContaining({ method: "PATCH" }));
    expect(refresh).toHaveBeenCalled();
  });
  it("shows API errors inline instead of a browser dialog", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "Blocking guardrail failures must be fixed before approval." }), {
        status: 409,
      }),
    );
    render(<ActionButton path="/drafts/1/transition">Approve</ActionButton>);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Blocking guardrail");
  });
});
