import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Settings } from "../Settings";

const apiMock = vi.hoisted(() => ({
  getLLMSettings: vi.fn(),
  getDataSourceSettings: vi.fn(),
  getChannelStatus: vi.fn(),
  startChannels: vi.fn(),
  stopChannels: vi.fn(),
  updateLLMSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
    isAuthRequiredError: vi.fn(() => false),
  };
});

vi.mock("@/lib/apiAuth", () => ({
  getApiAuthKey: vi.fn(() => ""),
  setApiAuthKey: vi.fn(),
}));

function llmSettings(overrides = {}) {
  return {
    provider: "openrouter",
    model_name: "deepseek/deepseek-v3.2",
    base_url: "https://openrouter.ai/api/v1",
    api_key_env: "OPENROUTER_API_KEY",
    api_key_configured: false,
    api_key_required: true,
    temperature: 0.1,
    timeout_seconds: 120,
    max_retries: 2,
    reasoning_effort: "",
    sse_timeout_seconds: 300,
    swarm_single_agent_mode: false,
    env_path: "agent/.env",
    providers: [
      {
        name: "openrouter",
        label: "OpenRouter",
        api_key_env: "OPENROUTER_API_KEY",
        base_url_env: "OPENROUTER_BASE_URL",
        default_model: "deepseek/deepseek-v3.2",
        default_base_url: "https://openrouter.ai/api/v1",
        api_key_required: true,
        auth_type: "api_key",
      },
    ],
    ...overrides,
  };
}

function dataSourceSettings() {
  return {
    tushare_token_configured: false,
    baostock_supported: true,
    baostock_installed: true,
    baostock_message: "BaoStock available",
    env_path: "agent/.env",
  };
}

function channelStatus() {
  return {
    running: false,
    inbound_queue: 0,
    outbound_queue: 0,
    session_count: 0,
    channels: {},
  };
}

describe("Settings single-agent mode toggle", () => {
  beforeEach(() => {
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
    apiMock.getChannelStatus.mockResolvedValue(channelStatus());
  });

  it("loads the persisted value into the checkbox", async () => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings({ swarm_single_agent_mode: true }));

    render(<Settings />);

    const checkbox = await screen.findByRole("checkbox", {
      name: /Single-agent mode \(disable concurrent swarm runs\)/,
    });
    expect(checkbox).toBeChecked();
  });

  it("persists the toggle via updateLLMSettings when saved", async () => {
    apiMock.getLLMSettings.mockResolvedValue(llmSettings());
    apiMock.updateLLMSettings.mockResolvedValue(llmSettings({ swarm_single_agent_mode: true }));

    render(<Settings />);

    const checkbox = await screen.findByRole("checkbox", {
      name: /Single-agent mode \(disable concurrent swarm runs\)/,
    });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    const form = checkbox.closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() =>
      expect(apiMock.updateLLMSettings).toHaveBeenCalledWith(
        expect.objectContaining({ swarm_single_agent_mode: true }),
      ),
    );
  });
});
