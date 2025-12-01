import json
import os
import sys
import boto3
import argparse
from datetime import datetime
import glob

class SessionRollback:
    def __init__(self):
        self.current_user = 'varadharajaan'

    def list_available_sessions(self):
        session_files = glob.glob("session_*.json")
        if not session_files:
            print("[ERROR] No session files found")
            return []
        sessions = []
        for session_file in session_files:
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                    sessions.append({
                        'file': session_file,
                        'session_id': session_data['session_id'],
                        'created_at': session_data['created_at'],
                        'user': session_data.get('user', 'Unknown'),
                        'resource_count': len(session_data.get('created_resources', [])),
                        'dry_run': session_data.get('dry_run', False)
                    })
            except Exception as e:
                print(f"[WARN] Could not read session file {session_file}: {e}")
        sessions.sort(key=lambda x: x['created_at'], reverse=True)
        return sessions

    def display_sessions(self, sessions):
        print("\n[LIST] Available Sessions:")
        print("="*80)
        print(f"{'#':<3} {'Session ID':<25} {'Created':<20} {'User':<15} {'Resources':<10} {'Type':<8}")
        print("-"*80)
        for i, session in enumerate(sessions, 1):
            created_at = session['created_at'][:19] if session['created_at'] else 'Unknown'
            session_type = 'DRY-RUN' if session['dry_run'] else 'REAL'
            print(f"{i:<3} {session['session_id']:<25} {created_at:<20} {session['user']:<15} {session['resource_count']:<10} {session_type:<8}")

    def select_session(self, sessions):
        while True:
            try:
                choice = input(f"\nSelect session to rollback (1-{len(sessions)}, or 'q' to quit): ").strip()
                if choice.lower() == 'q':
                    return None
                choice_num = int(choice)
                if 1 <= choice_num <= len(sessions):
                    return sessions[choice_num - 1]
                else:
                    print(f"[ERROR] Please enter a number between 1 and {len(sessions)}")
            except ValueError:
                print("[ERROR] Please enter a valid number or 'q' to quit")

    def load_session_resources(self, session_file):
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
                return session_data.get('created_resources', [])
        except Exception as e:
            print(f"[ERROR] Error loading session file: {e}")
            return []

    def display_session_resources(self, resources):
        print(f"\n[STATS] Resources in Session ({len(resources)} total):")
        print("-"*60)
        resource_types = {}
        for resource in resources:
            rtype = resource['resource_type']
            if rtype not in resource_types:
                resource_types[rtype] = []
            resource_types[rtype].append(resource)
        for rtype, res_list in resource_types.items():
            print(f"\n{rtype.upper()}S ({len(res_list)}):")
            for resource in res_list:
                print(f"   • {resource['resource_id']} ({resource['account']} - {resource['region']})")

    def confirm_rollback(self, resources):
        print(f"\n[WARN] WARNING: This will DELETE {len(resources)} resources!")
        print("This action cannot be undone.")
        confirm1 = input("\nAre you sure you want to proceed? (yes/no): ").strip().lower()
        if confirm1 != 'yes':
            return False
        confirm2 = input("Type 'DELETE' to confirm resource deletion: ").strip()
        return confirm2 == 'DELETE'

    def delete_resource(self, resource):
        resource_type = resource['resource_type']
        resource_id = resource['resource_id']
        try:
            if resource_type == 'instance':
                ec2_client = boto3.client(
                    'ec2',
                    aws_access_key_id=resource['access_key'],
                    aws_secret_access_key=resource['secret_key'],
                    region_name=resource['region']
                )
                print(f"   [DELETE] Terminating instance {resource_id}...")
                ec2_client.terminate_instances(InstanceIds=[resource_id])
                return True
            elif resource_type == 'auto-scaling-group':
                asg_client = boto3.client(
                    'autoscaling',
                    aws_access_key_id=resource['access_key'],
                    aws_secret_access_key=resource['secret_key'],
                    region_name=resource['region']
                )
                print(f"   [DELETE] Deleting ASG {resource_id}...")
                asg_client.update_auto_scaling_group(
                    AutoScalingGroupName=resource_id,
                    DesiredCapacity=0,
                    MinSize=0
                )
                import time
                time.sleep(2)
                asg_client.delete_auto_scaling_group(
                    AutoScalingGroupName=resource_id,
                    ForceDelete=True
                )
                return True
            elif resource_type == 'launch-template':
                ec2_client = boto3.client(
                    'ec2',
                    aws_access_key_id=resource['access_key'],
                    aws_secret_access_key=resource['secret_key'],
                    region_name=resource['region']
                )
                print(f"   [DELETE] Deleting launch template {resource_id}...")
                ec2_client.delete_launch_template(LaunchTemplateId=resource_id)
                return True
            else:
                print(f"   [WARN] Unknown resource type: {resource_type}")
                return False
        except Exception as e:
            print(f"   [ERROR] Failed to delete {resource_type} {resource_id}: {e}")
            return False

    def rollback_session(self, session_file):
        resources = self.load_session_resources(session_file)
        if not resources:
            print("[ERROR] No resources found in session")
            return False
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
                if session_data.get('dry_run', False):
                    print("[ERROR] This was a DRY-RUN session - no actual resources to delete")
                    return False
        except:
            pass
        self.display_session_resources(resources)
        if not self.confirm_rollback(resources):
            print("[ERROR] Rollback cancelled")
            return False
        print(f"\n🔄 Starting rollback of {len(resources)} resources...")
        success_count = 0
        failure_count = 0
        for resource in reversed(resources):
            try:
                if self.delete_resource(resource):
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as e:
                print(f"   [ERROR] Error deleting {resource['resource_id']}: {e}")
                failure_count += 1
        print(f"\n[STATS] Rollback Results:")
        print(f"   [OK] Successfully deleted: {success_count}")
        print(f"   [ERROR] Failed to delete: {failure_count}")
        if success_count > 0:
            archive_name = f"rolled_back_{session_file}"
            os.rename(session_file, archive_name)
            print(f"   [FILE] Session file archived as: {archive_name}")
        return success_count > 0

def main():
    parser = argparse.ArgumentParser(description='Session Rollback Tool')
    parser.add_argument('--rollback', action='store_true', help='Start rollback for session')
    args = parser.parse_args()

    tool = SessionRollback()
    sessions = tool.list_available_sessions()
    if not sessions:
        return
    tool.display_sessions(sessions)
    session = tool.select_session(sessions)
    if session:
        tool.rollback_session(session['file'])

if __name__ == "__main__":
    main()
