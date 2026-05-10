import unittest
import os
import shutil
import tempfile
from pathlib import Path

# Import the agent script
import importlib.util
import sys

# Add the agent directory to path so we can import the script
AGENT_DIR = Path(__file__).parent.absolute()
spec = importlib.util.spec_from_file_location("agent", AGENT_DIR / "gravitylan-agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class TestAgentCollectors(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.proc_dir = Path(self.test_dir) / "proc"
        self.sys_dir = Path(self.test_dir) / "sys"
        self.proc_dir.mkdir(parents=True)
        self.sys_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_collect_cpu(self):
        # Create mock /proc/stat
        stat_file = self.proc_dir / "stat"
        
        # First sample
        stat_file.write_text("cpu  100 0 50 1000 0 0 0 0\n")
        val1 = agent.collect_cpu(root_path=self.test_dir)
        self.assertEqual(val1, 0.0) # First call always 0.0
        
        # Second sample (increased total by 100, idle by 50 -> 50% usage)
        stat_file.write_text("cpu  125 0 75 1050 0 0 0 0\n")
        val2 = agent.collect_cpu(root_path=self.test_dir)
        self.assertEqual(val2, 50.0)

    def test_collect_ram(self):
        # Create mock /proc/meminfo
        mem_file = self.proc_dir / "meminfo"
        mem_file.write_text(
            "MemTotal:        16000000 kB\n"
            "MemAvailable:     8000000 kB\n"
        )
        
        ram = agent.collect_ram(root_path=self.test_dir)
        self.assertEqual(ram["total_mb"], 15625) # 16000000 / 1024
        self.assertEqual(ram["used_mb"], 7812)   # (16000000 - 8000000) / 1024
        self.assertEqual(ram["percent"], 50.0)

    def test_collect_network(self):
        # Create mock /proc/net/dev
        net_file = self.proc_dir / "net"
        net_file.mkdir(parents=True)
        dev_file = net_file / "dev"
        
        # First sample
        dev_file.write_text(
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "  eth0:    1000      10    0    0    0     0          0         0     2000      20    0    0    0     0       0          0\n"
        )
        agent._prev_net = None # Reset global
        agent.collect_network(root_path=self.test_dir)
        
        # Second sample (+100 rx, +200 tx)
        dev_file.write_text(
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "  eth0:    1100      11    0    0    0     0          0         0     2200      22    0    0    0     0       0          0\n"
        )
        net = agent.collect_network(root_path=self.test_dir)
        self.assertEqual(net["eth0"]["rx_bytes_sec"], 100)
        self.assertEqual(net["eth0"]["tx_bytes_sec"], 200)

    def test_collect_temperature(self):
        # Create mock /sys/class/thermal
        thermal_dir = self.sys_dir / "class" / "thermal" / "thermal_zone0"
        thermal_dir.mkdir(parents=True)
        
        (thermal_dir / "type").write_text("cpu-thermal\n")
        (thermal_dir / "temp").write_text("45500\n")
        
        temp = agent.collect_temperature(root_path=self.test_dir)
        self.assertEqual(temp, 45.5)

if __name__ == "__main__":
    unittest.main()
