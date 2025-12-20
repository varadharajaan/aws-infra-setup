#!/usr/bin/env python3
"""
Test suite for EKS Cluster Manager
Tests critical paths in cluster creation flow
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import os

# Add parent directory to path to import EKSClusterManager
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eks_cluster_manager import EKSClusterManager
from aws_credential_manager import CredentialInfo

class TestEKSClusterManager(unittest.TestCase):
    """Test cases for EKS Cluster Manager"""
    
    def setUp(self):
        """Set up test environment before each test"""
        # Create a mock config file
        self.config_file = "test_config.json"
        with open(self.config_file, "w") as f:
            json.dump({"test": "config"}, f)
        
        # Create EKSClusterManager instance with mock config
        self.manager = EKSClusterManager(config_file=self.config_file, current_user="test-user")
        
        # Mock credential info
        self.credential_info = MagicMock(spec=CredentialInfo)
        self.credential_info.regions = ["us-west-2"]
        self.credential_info.access_key = "test-access-key"
        self.credential_info.secret_key = "test-secret-key"
        self.credential_info.account_id = "123456789012"
        self.credential_info.account_name = "test-account"
        self.credential_info.credential_type = "IAM"
        self.credential_info.email = "test@example.com"
        self.credential_info.username = "test-user"
        
        # Mock cluster configuration
        self.cluster_config = {
            'credential_info': self.credential_info,
            'eks_version': "1.33",
            'ami_type': "AL2023_x86_64_STANDARD",
            'nodegroup_strategy': "spot",
            'instance_selections': {
                'spot': ['c6a.large', 'c5a.large'],
                'on-demand': ['c6a.large']
            },
            'min_nodes': 1,
            'desired_nodes': 1,
            'max_nodes': 3
        }
    
    def tearDown(self):
        """Clean up test environment after each test"""
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
    
    @patch('boto3.Session')
    def test_create_eks_control_plane(self, mock_session):
        """Test creation of EKS control plane"""
        # Mock EKS client
        mock_eks_client = MagicMock()
        mock_session.return_value.client.return_value = mock_eks_client
        
        # Test successful creation
        mock_eks_client.create_cluster.return_value = {"cluster": {"name": "test-cluster"}}
        mock_eks_client.get_waiter.return_value.wait.return_value = None
        
        result = self.manager.create_eks_control_plane(
            mock_eks_client,
            "test-cluster",
            "1.33",
            "arn:aws:iam::123456789012:role/eks-service-role",
            ["subnet-1", "subnet-2"],
            "sg-12345"
        )
        
        self.assertTrue(result)
        mock_eks_client.create_cluster.assert_called_once()
        mock_eks_client.get_waiter.assert_called_once_with('cluster_active')
    
    @patch('boto3.Session')
    def test_create_nodegroup(self, mock_session):
        """Test creation of nodegroup"""
        # Mock EKS client
        mock_eks_client = MagicMock()
        mock_session.return_value.client.return_value = mock_eks_client
        
        # Test spot nodegroup creation
        mock_eks_client.create_nodegroup.return_value = {"nodegroup": {"name": "test-nodegroup"}}
        mock_eks_client.get_waiter.return_value.wait.return_value = None
        
        result = self.manager.create_spot_nodegroup(
            mock_eks_client,
            "test-cluster",
            "test-nodegroup",
            "arn:aws:iam::123456789012:role/NodeInstanceRole",
            ["subnet-1", "subnet-2"],
            "AL2023_x86_64_STANDARD",
            ["c6a.large", "c5a.large"],
            1, 1, 8
        )
        
        self.assertTrue(result)
        mock_eks_client.create_nodegroup.assert_called_once()
        mock_eks_client.get_waiter.assert_called_once_with('nodegroup_active')
    
    @patch('subprocess.run')
    @patch('boto3.Session')
    def test_deploy_cloudwatch_agent(self, mock_session, mock_run):
        """Test deployment of CloudWatch agent"""
        # Setup mock subprocess run
        mock_run.return_value.returncode = 0
        
        # Call the method
        result = self.manager.deploy_cloudwatch_agent(
            "test-cluster",
            "us-west-2",
            "test-access-key",
            "test-secret-key",
            "123456789012"
        )
        
        # Verify the result
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 5)  # kubeconfig update + 4 kubectl applies
    
    @patch('boto3.Session')
    def test_setup_cloudwatch_alarms(self, mock_session):
        """Test setup of CloudWatch alarms"""
        # Mock CloudWatch client
        mock_cloudwatch_client = MagicMock()
        mock_session.return_value.client.return_value = mock_cloudwatch_client
        
        # Patch the create_composite_alarms method
        with patch.object(self.manager, 'create_composite_alarms', return_value=True):
            result = self.manager.setup_cloudwatch_alarms(
                "test-cluster",
                "us-west-2",
                mock_cloudwatch_client,
                "test-nodegroup",
                "123456789012"
            )
            
            # Verify the result
            self.assertTrue(result)
            self.assertEqual(mock_cloudwatch_client.put_metric_alarm.call_count, 7)
    
    @patch('boto3.Session')
    def test_setup_cost_alarms(self, mock_session):
        """Test setup of cost monitoring alarms"""
        # Mock CloudWatch client
        mock_cloudwatch_client = MagicMock()
        mock_session.return_value.client.return_value = mock_cloudwatch_client
        
        result = self.manager.setup_cost_alarms(
            "test-cluster",
            "us-west-2",
            mock_cloudwatch_client,
            "123456789012"
        )
        
        # Verify the result
        self.assertTrue(result)
        self.assertEqual(mock_cloudwatch_client.put_metric_alarm.call_count, 4)
    
    @patch('boto3.Session')
    @patch.object(EKSClusterManager, 'create_eks_control_plane', return_value=True)
    @patch.object(EKSClusterManager, 'ensure_iam_roles', return_value=('role1', 'role2'))
    @patch.object(EKSClusterManager, 'get_or_create_vpc_resources', return_value=(['subnet1', 'subnet2'], 'sg1'))
    @patch.object(EKSClusterManager, 'create_spot_nodegroup', return_value=True)
    @patch.object(EKSClusterManager, 'configure_aws_auth_configmap', return_value=True)
    @patch.object(EKSClusterManager, 'install_essential_addons', return_value=True)
    @patch.object(EKSClusterManager, 'enable_container_insights', return_value=True)
    @patch.object(EKSClusterManager, 'setup_cluster_autoscaler', return_value=True)
    @patch.object(EKSClusterManager, 'setup_scheduled_scaling', return_value=True)
    @patch.object(EKSClusterManager, 'deploy_cloudwatch_agent', return_value=True)
    @patch.object(EKSClusterManager, 'setup_cloudwatch_alarms', return_value=True)
    @patch.object(EKSClusterManager, 'setup_cost_alarms', return_value=True)
    @patch.object(EKSClusterManager, 'health_check_cluster', return_value={'overall_healthy': True, 'summary': {'health_score': 95}})
    @patch.object(EKSClusterManager, 'save_cluster_details')
    @patch.object(EKSClusterManager, 'generate_user_instructions')
    @patch.object(EKSClusterManager, 'print_enhanced_cluster_summary')
    def test_create_cluster_integration(self, *mocks):
        """Integration test for create_cluster method"""
        # Call the create_cluster method
        result = self.manager.create_cluster(self.cluster_config)
        
        # Verify the result
        self.assertTrue(result)
        
        # Verify all the mocked methods were called
        for mock in mocks:
            mock.assert_called()
    
    @patch('boto3.Session')
    @patch.object(EKSClusterManager, 'create_eks_control_plane', return_value=False)
    def test_create_cluster_failure(self, mock_create_control_plane, mock_session):
        """Test cluster creation failure"""
        # Call the create_cluster method with a failing control plane creation
        result = self.manager.create_cluster(self.cluster_config)
        
        # Verify the result
        self.assertFalse(result)

if __name__ == '__main__':
    # Run the tests
    unittest.main()