import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent_app'))
sys.path.insert(0, str(ROOT))

from agent_app.utils import setup_logging


class AgentLoggingPathTests(unittest.TestCase):
    def test_setup_logging_expands_environment_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['SAHAR_AGENT_LOG_TMP'] = tmp
            setup_logging('$SAHAR_AGENT_LOG_TMP/agent.log')
            self.assertTrue(os.path.exists(os.path.join(tmp, 'agent.log')))


if __name__ == '__main__':
    unittest.main()
