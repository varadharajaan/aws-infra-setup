#!/bin/bash

# ⚠️ NUCLEAR OPTION: Force delete all CloudWatch alarms (Metric + Composite)
# Date: 2025-07-29
# Author: varadharajaan

REGIONS=("us-east-1" "us-east-2" "us-west-1" "us-west-2"
         "ap-south-1" "ap-southeast-1" "ap-southeast-2"
         "ap-northeast-1" "ap-northeast-2"
         "eu-west-1" "eu-west-2" "eu-west-3"
         "eu-central-1" "eu-north-1" "sa-east-1")

echo "🚨 NUCLEAR OPERATION: Force deleting ALL CloudWatch alarms"
echo "⚠️  This will delete EVERYTHING without confirmation!"
echo "User: varadharajaan"
echo "Started at: $(date)"
echo ""

for region in "${REGIONS[@]}"; do
  echo "🔥 NUKING region: $region"

  # Delete Composite Alarms
  composite_alarms=$(aws cloudwatch describe-alarms --region "$region" --alarm-types CompositeAlarm \
                     --query 'CompositeAlarms[].AlarmName' --output text 2>/dev/null)
  if [ -n "$composite_alarms" ]; then
    echo "🧨 Deleting composite alarms..."
    IFS=$'\t' read -r -a comp_array <<< "$composite_alarms"
    for alarm in "${comp_array[@]}"; do
      echo "➡️  Deleting composite alarm: $alarm"
      aws cloudwatch delete-alarms --region "$region" --alarm-names "$alarm" 2>/dev/null || \
      echo "❌ Failed to delete composite alarm: $alarm"
    done
  else
    echo "✅ No composite alarms found."
  fi

  sleep 1

  # Delete Metric Alarms
  metric_alarms=$(aws cloudwatch describe-alarms --region "$region" --alarm-types MetricAlarm \
                   --query 'MetricAlarms[].AlarmName' --output text 2>/dev/null)
  if [ -n "$metric_alarms" ]; then
    echo "🧨 Deleting metric alarms..."
    IFS=$'\t' read -r -a metric_array <<< "$metric_alarms"
    for alarm in "${metric_array[@]}"; do
      echo "➡️  Deleting metric alarm: $alarm"
      aws cloudwatch delete-alarms --region "$region" --alarm-names "$alarm" 2>/dev/null || \
      echo "❌ Failed to delete metric alarm: $alarm"
    done
  else
    echo "✅ No metric alarms found."
  fi

  echo "✅ Region $region NUKED!"
  echo ""
done

echo "💥 NUCLEAR DELETION COMPLETED!"
echo "All CloudWatch alarms (metric and composite) should now be deleted."
