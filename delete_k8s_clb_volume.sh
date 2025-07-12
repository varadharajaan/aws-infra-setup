#!/bin/bash

regions=("us-east-1" "us-east-2" "us-west-1" "us-west-2" \
"ap-south-1" "eu-central-1" "eu-west-1" "eu-west-2" \
"eu-west-3" "ap-southeast-1" "ap-southeast-2" \
"ap-northeast-1" "ap-northeast-2" "sa-east-1")

for region in "${regions[@]}"; do
  echo "Processing region: $region"

  # Delete Classic Load Balancers (ELB v1)
  elbs=$(aws elb describe-load-balancers --region "$region" --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text)
  for elb in $elbs; do
    echo "Deleting ELB: $elb in region $region"
    aws elb delete-load-balancer --load-balancer-name "$elb" --region "$region"
  done

  # Delete unattached EBS volumes
  volumes=$(aws ec2 describe-volumes --region "$region" --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text)
  for volume in $volumes; do
    echo "Deleting unattached volume: $volume in region $region"
    aws ec2 delete-volume --volume-id "$volume" --region "$region"
  done

done