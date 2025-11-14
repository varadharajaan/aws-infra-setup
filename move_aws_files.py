import logging
import os
import re
import shutil

# Files to ignore (add any more if needed)
ignore_files = {"ec2_cleanup_script.py"}

# Configure logging
logging.basicConfig(
    filename="file_organizer.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Patterns and their respective folders
patterns_to_folders = [
    # EKS related
    (
        re.compile(
            r"^(kubectl_commands_|eks_creation_log|eks_deletion_log|eks_clusters_simple|eks_clusters_created|eks_cluster_created_|eks_deletion_report_).*\.(json|txt)?$",
            re.IGNORECASE,
        ),
        "eks",
    ),
    # EC2 related
    (
        re.compile(
            r"^(ec2_instance_report|ec2_creation_log|cost_calculations|iam_user_instance_mapping_|ultra_ec2_cleanup_report_|ec2_instance_report_|ec2_instances_report_|ec2_report_|aws_account_info_).*\.(json|txt)?$",
            re.IGNORECASE,
        ),
        "ec2",
    ),
    # Also catch ec2_creation_log with or without extension or number
    (re.compile(r"^ec2_creation_log.*(\.json|\.txt)?$", re.IGNORECASE), "ec2"),
    # ELB related
    (
        re.compile(
            r"^(elb_cleanup_log|elb_deletion_report).*\.(json|txt)?$", re.IGNORECASE
        ),
        "elb",
    ),
    # IAM related
    (
        re.compile(
            r"^(iam_cleanup_report|iam_deletion_report|user_instructions_).*\.(json|txt)?$",
            re.IGNORECASE,
        ),
        "iam",
    ),
    # Ultra EC2 cleanup
    (re.compile(r"^(ultra_ec2_cleanup_).*", re.IGNORECASE), "ec2"),
    # AWS resource creation logs
    (re.compile(r"^(aws_resource_creation_).*", re.IGNORECASE), "ec2"),
    # EC2 cleanup logs
    (re.compile(r"^(ec2_cleanup_).*", re.IGNORECASE), "ec2"),
    # EKS cleanup logs
    (re.compile(r"^(eks_deletion_log).*", re.IGNORECASE), "eks"),
]

files_in_dir = [f for f in os.listdir(".") if os.path.isfile(f)]

moved_files = 0
skipped_files = 0

for fname in files_in_dir:
    if fname in ignore_files:
        logging.info(f"Ignored file (in ignore list): {fname}")
        print(f"Ignored: {fname}")
        skipped_files += 1
        continue

    moved = False
    for pattern, folder in patterns_to_folders:
        if pattern.match(fname):
            if not os.path.isdir(folder):
                os.makedirs(folder)
                logging.info(f"Created directory: {folder}")
            dest_path = os.path.join(folder, fname)
            shutil.move(fname, dest_path)
            logging.info(f"Moved file {fname} -> {dest_path}")
            print(f"Moved: {fname} -> {folder}/")
            moved = True
            moved_files += 1
            break
    if not moved:
        logging.info(f"No matching pattern for file: {fname}")

if moved_files == 0:
    print("No files matched patterns or files already organized.")
else:
    print(f"\nTotal files moved: {moved_files}")
    logging.info(f"Total files moved: {moved_files}")
if skipped_files:
    print(f"Skipped {skipped_files} files (ignored list).")
