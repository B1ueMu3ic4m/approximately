"""Framework adapters (opt-in integrations).

Everything here imports the target framework lazily: the core package stays
dependency-free, and each adapter only activates when its framework is
installed.
"""
