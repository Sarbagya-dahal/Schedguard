"""Hard limits. They mirror what a real eBPF backend can express (fixed-size
tables, bounded values). The safety pass enforces them before anything else."""
MAX_CLASSES = 16
PRIO_RANGE = (0, 7)          # 0 = most urgent tier
QUANTUM_MS_RANGE = (1, 1000)
AGING_MS_RANGE = (1, 60_000)
BOUND_MS_RANGE = (1, 600_000)
SHARE_PCT_RANGE = (1, 100)
MAX_TASKS_RANGE = (1, 256)
DEFAULT_MAX_TASKS = 16
INF = 10**9                  # "unbounded" marker used by the analysis
