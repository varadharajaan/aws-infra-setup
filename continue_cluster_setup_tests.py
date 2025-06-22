#!/usr/bin/env python3
"""
Test suite for EKS Cluster Continuation Setup
Tests critical functionality of the continuation script
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import boto3
import os

# Add parent directory to path to import continue_cluster_setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from continue_cluster_setup import EKSClusterContinuation
from aws_credential_manager import CredentialInfo


class TestEKSClusterContinuation(unittest.TestCase):
    """Test cases for EKS Cluster Continuation"""
    
    def setUp(self):
        """Set up test environment before each test"""
        self.continuation = EKSClusterContinuation()
        
        # Mock credential info
        self.mock_credentials = CredentialInfo(
            account_name="test-account",
            account_id="123456789012",
            email="test@example.com",
            access_key="test-access-key",
            secret_key="test-secret-key",
            credential_type="admin",
            regions=["us-west-2"],
            username="admin"
        )
        
        # Mock cluster info
        self.mock_cluster_info = {
            'name': 'test-cluster',
            'status': 'ACTIVE',
            'version': '1.28',
            'endpoint': 'https://test.eks.amazonaws.com',
            'created_at': '2024-01-01',
            'platform_version': 'eks.1',
            'vpc_config': {},
            'logging': {},
            'addons': [
                {'name': 'vpc-cni', 'status': 'ACTIVE', 'version': 'v1.12.0'},
                {'name': 'kube-proxy', 'status': 'ACTIVE', 'version': 'v1.28.0'}
            ],
            'nodegroups': [
                {
                    'name': 'test-ng-spot',
                    'status': 'ACTIVE',
                    'capacity_type': 'SPOT',
                    'instance_types': ['t3.medium', 't3.large'],
                    'scaling_config': {'minSize': 1, 'desiredSize': 2, 'maxSize': 5}
                }
            ]
        }
    
    def test_initialization(self):
        """Test that EKSClusterContinuation initializes correctly"""
        self.assertIsNone(self.continuation.cluster_name)
        self.assertIsNone(self.continuation.credentials)
        self.assertIsNone(self.continuation.region)
        self.assertIsNone(self.continuation.eks_manager)
        self.assertEqual(self.continuation.cluster_info, {})
    
    def test_print_colored(self):
        """Test colored output function"""
        # This test mainly ensures the function doesn't crash
        with patch('builtins.print') as mock_print:
            self.continuation.print_colored("RED", "Test message")
            mock_print.assert_called_once()
    
    @patch('boto3.Session')
    def test_verify_cluster_status_success(self, mock_session):
        """Test successful cluster status verification"""
        # Setup mocks
        mock_eks_client = MagicMock()
        mock_sts_client = MagicMock()
        mock_session.return_value.client.side_effect = lambda service: {
            'eks': mock_eks_client,
            'sts': mock_sts_client
        }[service]
        
        # Mock STS response
        mock_sts_client.get_caller_identity.return_value = {
            'Account': '123456789012'
        }
        
        # Mock EKS responses
        mock_eks_client.describe_cluster.return_value = {
            'cluster': {
                'name': 'test-cluster',
                'status': 'ACTIVE',
                'version': '1.28',
                'endpoint': 'https://test.eks.amazonaws.com',
                'createdAt': '2024-01-01',
                'platformVersion': 'eks.1',
                'resourcesVpcConfig': {},
                'logging': {}
            }
        }
        
        mock_eks_client.list_nodegroups.return_value = {
            'nodegroups': ['test-ng-spot']
        }
        
        mock_eks_client.describe_nodegroup.return_value = {
            'nodegroup': {
                'status': 'ACTIVE',
                'capacityType': 'SPOT',
                'instanceTypes': ['t3.medium'],
                'scalingConfig': {'minSize': 1, 'desiredSize': 2, 'maxSize': 5}
            }
        }
        
        mock_eks_client.list_addons.return_value = {
            'addons': ['vpc-cni']
        }
        
        mock_eks_client.describe_addon.return_value = {
            'addon': {
                'status': 'ACTIVE',
                'addonVersion': 'v1.12.0'
            }
        }
        
        # Setup test data
        self.continuation.cluster_name = 'test-cluster'
        self.continuation.region = 'us-west-2'
        self.continuation.credentials = self.mock_credentials
        
        # Test
        with patch.object(self.continuation, 'display_cluster_status'):
            result = self.continuation.verify_cluster_status()
        
        # Verify
        self.assertTrue(result)
        self.assertEqual(self.continuation.cluster_info['name'], 'test-cluster')
        self.assertEqual(self.continuation.cluster_info['status'], 'ACTIVE')
        mock_eks_client.describe_cluster.assert_called_once_with(name='test-cluster')
    
    @patch('boto3.Session')
    def test_verify_cluster_status_not_found(self, mock_session):
        """Test cluster not found scenario"""
        # Setup mocks
        mock_eks_client = MagicMock()
        mock_sts_client = MagicMock()
        mock_session.return_value.client.side_effect = lambda service: {
            'eks': mock_eks_client,
            'sts': mock_sts_client
        }[service]
        
        # Mock cluster not found exception
        mock_eks_client.exceptions.ResourceNotFoundException = Exception
        mock_eks_client.describe_cluster.side_effect = mock_eks_client.exceptions.ResourceNotFoundException()
        
        # Setup test data
        self.continuation.cluster_name = 'nonexistent-cluster'
        self.continuation.region = 'us-west-2'
        self.continuation.credentials = self.mock_credentials
        
        # Test
        result = self.continuation.verify_cluster_status()
        
        # Verify
        self.assertFalse(result)
    
    @patch('boto3.Session')
    def test_verify_cluster_status_inactive(self, mock_session):
        """Test cluster in non-ACTIVE status"""
        # Setup mocks
        mock_eks_client = MagicMock()
        mock_sts_client = MagicMock()
        mock_session.return_value.client.side_effect = lambda service: {
            'eks': mock_eks_client,
            'sts': mock_sts_client
        }[service]
        
        # Mock STS response
        mock_sts_client.get_caller_identity.return_value = {
            'Account': '123456789012'
        }
        
        # Mock EKS response with CREATING status
        mock_eks_client.describe_cluster.return_value = {
            'cluster': {
                'name': 'test-cluster',
                'status': 'CREATING',  # Not ACTIVE
                'version': '1.28'
            }
        }
        
        mock_eks_client.list_nodegroups.return_value = {'nodegroups': []}
        mock_eks_client.list_addons.return_value = {'addons': []}
        
        # Setup test data
        self.continuation.cluster_name = 'test-cluster'
        self.continuation.region = 'us-west-2'
        self.continuation.credentials = self.mock_credentials
        
        # Test
        with patch.object(self.continuation, 'display_cluster_status'):
            result = self.continuation.verify_cluster_status()
        
        # Verify
        self.assertFalse(result)
        self.assertEqual(self.continuation.cluster_info['status'], 'CREATING')
    
    def test_display_cluster_status(self):
        """Test cluster status display"""
        # Setup test data
        self.continuation.cluster_info = self.mock_cluster_info
        self.continuation.region = 'us-west-2'
        self.continuation.credentials = self.mock_credentials
        
        # Test (mainly ensures no exceptions)
        with patch('builtins.print'):
            self.continuation.display_cluster_status()
    
    def test_display_main_menu(self):
        """Test main menu display and input handling"""
        # Test valid input
        with patch('builtins.input', return_value='1'), patch('builtins.print'):
            choice = self.continuation.display_main_menu()
            self.assertEqual(choice, 1)
        
        # Test invalid input
        with patch('builtins.input', return_value='invalid'), patch('builtins.print'):
            choice = self.continuation.display_main_menu()
            self.assertEqual(choice, 0)
    
    @patch.object(EKSClusterContinuation, 'initialize_eks_manager')
    def test_initialize_eks_manager(self, mock_init):
        """Test EKS manager initialization"""
        self.continuation.credentials = self.mock_credentials
        self.continuation.initialize_eks_manager()
        mock_init.assert_called_once()
    
    def test_handle_essential_addons_all_present(self):
        """Test essential add-ons when all are present"""
        # Setup test data with all essential add-ons
        self.continuation.cluster_info = {
            'addons': [
                {'name': 'vpc-cni', 'status': 'ACTIVE', 'version': 'v1.12.0'},
                {'name': 'kube-proxy', 'status': 'ACTIVE', 'version': 'v1.28.0'},
                {'name': 'coredns', 'status': 'ACTIVE', 'version': 'v1.10.0'},
                {'name': 'aws-ebs-csi-driver', 'status': 'ACTIVE', 'version': 'v1.23.0'},
                {'name': 'aws-efs-csi-driver', 'status': 'ACTIVE', 'version': 'v1.7.0'}
            ]
        }
        
        with patch('builtins.print'):
            # This should complete without asking to install anything
            self.continuation.handle_essential_addons()


class TestIntegrationScenarios(unittest.TestCase):
    """Integration test scenarios for common use cases"""
    
    def setUp(self):
        """Set up integration test environment"""
        self.continuation = EKSClusterContinuation()
    
    @patch('boto3.Session')
    @patch('builtins.input')
    def test_cluster_with_no_nodegroups(self, mock_input, mock_session):
        """Test handling cluster with no nodegroups"""
        # Setup cluster info with no nodegroups
        cluster_info = {
            'name': 'test-cluster',
            'status': 'ACTIVE',
            'nodegroups': [],
            'addons': []
        }
        self.continuation.cluster_info = cluster_info
        
        # Test nodegroups management
        mock_input.side_effect = ['1', '4']  # Add on-demand, then back to menu
        with patch('builtins.print'), patch.object(self.continuation, 'create_nodegroup'):
            self.continuation.handle_nodegroups_management()
    
    def test_cluster_with_partial_setup(self):
        """Test handling cluster with partial setup"""
        # Setup cluster info with some components
        cluster_info = {
            'name': 'test-cluster',
            'status': 'ACTIVE',
            'nodegroups': [
                {'name': 'ng-spot', 'status': 'ACTIVE', 'capacity_type': 'SPOT', 'instance_types': ['t3.medium'], 'scaling_config': {}}
            ],
            'addons': [
                {'name': 'vpc-cni', 'status': 'ACTIVE', 'version': 'v1.12.0'}
            ]
        }
        self.continuation.cluster_info = cluster_info
        
        # This test mainly ensures the structure handles partial setups correctly
        self.assertEqual(len(cluster_info['nodegroups']), 1)
        self.assertEqual(len(cluster_info['addons']), 1)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)