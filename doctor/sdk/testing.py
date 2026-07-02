from doctor.models import PluginResult
from doctor.plugins.base import DoctorPlugin


class PluginTestHarness:
    """Test harness for plugin authors (§22.4).

    Runs a plugin the same way the real doctor CLI does — through its
    public run()/is_supported() methods — so plugin authors write tests
    against the same contract the core enforces, without needing to
    understand core internals.
    """

    def run(self, plugin: DoctorPlugin) -> PluginResult:
        """Execute plugin.run() and return its PluginResult.

        Does NOT catch exceptions from run() itself. Per §6.4, a
        plugin's run() must never raise — it's responsible for catching
        its own exceptions and returning a FAIL PluginResult instead.
        A raised exception here means the plugin under test violates
        that contract, and the test should fail loudly, not have the
        harness silently absorb it.
        """
        return plugin.run()

    def check_is_supported(self, plugin: DoctorPlugin) -> bool:
        """Call is_supported(). Same reasoning as run(): this must not
        raise either, so exceptions propagate to the caller as-is."""
        return plugin.is_supported()