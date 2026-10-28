"""Check Steam device selection without mounting anything or using a GPU."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('steam_device_view',Path(__file__).resolve().parents[1]/'scripts/gpu-selector/steam_device_view.py')
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)


class DeviceViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dev=self.root/'dev';self.dev.mkdir()
        self.drm=self.root/'sys-drm';self.drm.mkdir()
        folder=self.root/'driver';info=folder/'information'
        self.driver=MagicMock();self.driver.__truediv__.return_value=folder
        info.parent.mkdir(parents=True);info.write_text('GPU UUID: GPU-selected-example\nDevice Minor: 7\n')
        for name in ('nvidia0','nvidia1','nvidia7','nvidiactl','nvidia-uvm'):(self.dev/name).touch()
        self.choice={'render_index':1,'render_pci':'00000000:01:00.0','render_uuid':'GPU-selected-example'}

    def test_uses_uuid_pci_and_kernel_minor_instead_of_assuming_index(self):
        with patch.object(Path,'is_char_device',return_value=True):
            plan=view.device_plan(self.choice,self.dev,self.drm,self.driver)
        self.assertEqual(plan['device'],str(self.dev/'nvidia7'))
        self.driver.__truediv__.assert_called_with('0000:01:00.0')
        self.assertEqual(set(plan['masked']),{str(self.dev/'nvidia0'),str(self.dev/'nvidia1')})
        self.assertTrue((self.dev/'nvidia0').exists())

    def test_keeps_only_selected_drm_nodes(self):
        (self.dev/'dri').mkdir()
        nodes=[]
        for name,pci in [('renderD130','0000:01:00.0'),('renderD129','0000:02:00.0')]:
            (self.dev/'dri'/name).touch()
            node=MagicMock();node.name=name
            node.__truediv__.return_value.resolve.return_value.name=pci;nodes.append(node)
        drm=MagicMock();drm.glob.return_value=nodes
        with patch.object(Path,'is_char_device',return_value=True):
            plan=view.device_plan(self.choice,self.dev,drm,self.driver)
        self.assertNotIn(str(self.dev/'dri/renderD130'),plan['masked'])
        self.assertIn(str(self.dev/'dri/renderD129'),plan['masked'])

    def test_wrong_uuid_fails_before_launch(self):
        with self.assertRaisesRegex(RuntimeError,'UUID/PCI/minor'):
            view.device_plan(dict(self.choice,render_uuid='GPU-other-example'),self.dev,self.drm,self.driver)

    def test_missing_selected_device_fails_before_launch(self):
        with self.assertRaisesRegex(RuntimeError,'device is unavailable'):
            view.device_plan(self.choice,self.dev,self.drm,self.driver)

    def test_child_args_and_network_remain_intact(self):
        plan={'masked':['/dev/nvidia0','/dev/dri/renderD128']}
        child=['/home/user/Steam Files/steam.sh','-shutdown','argument with spaces']
        with patch.object(view,'bubblewrap',return_value='/usr/bin/bwrap'):
            args=view.command(self.root,self.choice,plan,child)
        self.assertEqual(args[args.index('--')+1:],child)
        self.assertNotIn('--unshare-net',args);self.assertNotIn('--unshare-pid',args)
        self.assertNotIn('--die-with-parent',args)
        self.assertIn('GPUIP_DEVICE_VIEW',args)
        self.assertEqual(args[args.index('VKD3D_VULKAN_DEVICE')+1],'0')
        self.assertEqual(args.count('--ro-bind'),2)

    def test_pci_normalization_and_invalid_input(self):
        self.assertEqual(view.pci_address('00000000:B1:00.0'),'0000:b1:00.0')
        for value in ('../device','0000:01:40.0','00010000:01:00.0','0000:01:00.8'):
            with self.assertRaises(ValueError):view.pci_address(value)
