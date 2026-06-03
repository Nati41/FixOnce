import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
DASHBOARD_HTML = PROJECT_ROOT / "data" / "dashboard.html"


class TestDashboardWizardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = DASHBOARD_HTML.read_text(encoding="utf-8")

    def test_all_four_clients_have_open_labels(self):
        for label in ("Open Claude", "Open Cursor", "Open Codex", "Other AI tools"):
            self.assertIn(label, self.html)

    def test_wizard_card_has_no_clipping_rules(self):
        match = re.search(r"\.wizard-card\s*\{([^}]*)\}", self.html, re.DOTALL)
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertNotIn("overflow: hidden", block)
        self.assertNotIn("max-height", block)

    def test_open_button_click_handler_targets_existing_endpoint(self):
        self.assertIn("querySelectorAll('[data-open]')", self.html)
        self.assertIn("fetch(`${API}/api/setup/open-app/${client}`", self.html)
        self.assertIn("method: 'POST'", self.html)

    def test_retry_button_click_handler_targets_existing_endpoint(self):
        self.assertIn("querySelectorAll('[data-retry]')", self.html)
        self.assertIn("fetch(`${API}/api/setup/retry-ai/${client}`", self.html)
        self.assertIn("method: 'POST'", self.html)

    def test_repair_mcp_button_targets_repair_endpoint(self):
        self.assertIn("repairMcpBtn", self.html)
        self.assertIn("fetch(`${API}/api/setup/repair-mcp`", self.html)
        self.assertIn("open a new AI chat or reconnect MCP", self.html)

    def test_summary_card_exposes_manage_ai_integrations_entry(self):
        self.assertIn('id="aiSummaryTitle"', self.html)
        self.assertIn("AI integrations", self.html)
        self.assertIn("Connected to", self.html)
        self.assertIn("AI setup", self.html)

    def test_ai_integrations_settings_panel_reuses_client_list_ui(self):
        self.assertIn('id="aiIntegrationsCard"', self.html)
        self.assertIn('id="integrationsGrid"', self.html)
        self.assertIn("renderIntegrations(onboarding)", self.html)

    def test_wizard_visibility_is_controlled_by_server_flow_state(self):
        self.assertIn("const shouldShow = Boolean(onboarding.should_show_onboarding);", self.html)
        self.assertIn("!clients.length || onboardingDismissed || !shouldShow", self.html)

    def test_ui_renders_every_client_row_from_api_payload(self):
        self.assertIn("sortClientsForDisplay(clients).map(client =>", self.html)
        self.assertIn("getClientDisplayName(client.client)", self.html)
        self.assertIn("copy[`open_${client.client}`]", self.html)

    def test_header_and_agent_card_use_shared_actor_resolver(self):
        self.assertIn("const activeAI = getCurrentActorName(s, agentContext, primaryAI, setupFinalizing);", self.html)
        self.assertIn("const resolvedAgentName = activeAI;", self.html)
        self.assertIn("function isKnownActor(value)", self.html)
        self.assertIn("text !== 'unknown'", self.html)


if __name__ == "__main__":
    unittest.main()
