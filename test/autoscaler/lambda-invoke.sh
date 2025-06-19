#!/bin/bash

# Method 1: Direct JSON payload (recommended)
aws lambda invoke \
    --function-name eks-scale-diuh \
    --region us-west-1 \
    --payload '{
        "action": "scale_up",
        "ist_time": "10:17 AM IST",
        "nodegroups": [
            {
                "name": "nodegroup-1",
                "desired_size": 2,
                "min_size": 1,
                "max_size": 6
            }
        ]
    }' \
    response.json

echo "Scale-up response:"
cat response.json | jq . 2>/dev/null || cat response.json