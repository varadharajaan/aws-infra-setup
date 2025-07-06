#!/bin/bash

# Nuclear option: Force delete all alarms in batches
# Date: 2025-07-06 04:27:30 UTC
# User: varadharajaan

REGIONS=("us-east-1" "us-east-2" "us-west-1" "us-west-2" "ap-south-1")

echo "🚨 NUCLEAR OPTION: Force deleting ALL CloudWatch alarms"
echo "⚠️  This will delete EVERYTHING without confirmation!"
echo "Executed by: varadharajaan at $(date)"

for region in "${REGIONS[@]}"; do
  echo ""
  echo "🔥 NUKING region: $region"

  # Get all composite alarm names and delete them
  composite_alarms=$(aws cloudwatch describe-alarms --region $region --alarm-types CompositeAlarm --query 'CompositeAlarms[].AlarmName' --output text 2>/dev/null | tr '\t' ' ')
  if [ ! -z "$composite_alarms" ] && [ "$composite_alarms" != "None" ]; then
    echo "🗑️  Batch deleting composite alarms: $composite_alarms"
    aws cloudwatch delete-alarms --region $region --alarm-names $composite_alarms 2>/dev/null || true
  fi

  # Wait
  sleep 2

  # Get all metric alarm names and delete them
  metric_alarms=$(aws cloudwatch describe-alarms --region $region --alarm-types MetricAlarm --query 'MetricAlarms[].AlarmName' --output text 2>/dev/null | tr '\t' ' ')
  if [ ! -z "$metric_alarms" ] && [ "$metric_alarms" != "None" ]; then
    echo "🗑️  Batch deleting metric alarms: $metric_alarms"
    aws cloudwatch delete-alarms --region $region --alarm-names $metric_alarms 2>/dev/null || true
  fi

  echo "✅ Region $region NUKED!"
done

echo ""
echo "💥 NUCLEAR DELETION COMPLETED!"
echo "All CloudWatch alarms should be deleted across all regions."