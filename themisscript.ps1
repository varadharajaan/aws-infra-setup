# ================================================================================================
# THEMIS FILE MANAGEMENT SCRIPT - COMPLETE WITHOUT METADATA - PART 1
# Current Date and Time (UTC): 2025-08-12 05:09:26
# Current User: varadharajaan
# ================================================================================================



param(
    [Parameter(Mandatory=$false)]
    [string]$Phase = "1",
    [Parameter(Mandatory=$false)]
    [string]$FileType = "all",
    [Parameter(Mandatory=$false)]
    [switch]$DebugMode = $false,
    [Parameter(Mandatory=$false)]
    [int]$DaysBack = 0,
    [Parameter(Mandatory=$false)]
    [string]$InputFile = "",
    [Parameter(Mandatory=$false)]
    [int]$MaxThreads = 5,
    [Parameter(Mandatory=$false)]
    [string]$DestinationType = "local",
    [Parameter(Mandatory=$false)]
    [string]$ErrorFile = "",
    [Parameter(Mandatory=$false)]
    [switch]$RetryMode = $false,
    [Parameter(Mandatory=$false)]
    [switch]$UseMSAL = $false
)


# ================================================================================================
# TRANSCRIPT LOGGING - ADD THIS AT THE VERY BEGINNING OF YOUR SCRIPT
# ================================================================================================

# Create logs directory if it doesn't exist
$logsDir = Join-Path $PSScriptRoot "Logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# Start transcript with timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$transcriptFile = Join-Path $logsDir "ThemisScript_Transcript_$timestamp.log"

try {
    Start-Transcript -Path $transcriptFile -Append
    Write-Host "📝 Console transcript logging started: $transcriptFile" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Could not start transcript: $_" -ForegroundColor Yellow
}

# ================================================================================================
# MISSING HELPER FUNCTIONS
# ================================================================================================

function Parse-FileTypes {
    param([string]$FileTypeString)
    
    if ([string]::IsNullOrEmpty($FileTypeString)) {
        return @("V1Daily")
    }
    
    if ($FileTypeString -contains ',') {
        return $FileTypeString -split ',' | ForEach-Object { $_.Trim() }
    } else {
        return @($FileTypeString)
    }
}

function Load-ErrorFileForRetry {
    param([string]$ErrorFilePath)
    
    try {
        if (-not (Test-Path $ErrorFilePath)) {
            Write-Log -Message "Error file not found: $ErrorFilePath" -Level "ERROR" -Color Red
            return @()
        }
        
        $retryData = Import-Csv -Path $ErrorFilePath
        Write-Log -Message "Loaded $($retryData.Count) entries from error file" -Level "INFO" -Color Green
        return $retryData
        
    } catch {
        Write-Log -Message "Error loading retry file: $_" -Level "ERROR" -Color Red
        return @()
    }
}

function Save-ErrorFiles {
    param(
        [string]$OperationType,
        [object]$Results
    )
    
    try {
        # Ensure error directory exists
        if (-not (Test-Path $errorDir)) {
            New-Item -ItemType Directory -Path $errorDir -Force | Out-Null
        }
        
        $allResults = if ($Results -is [array]) { $Results } else { @($Results.ToArray()) }
        $failures = $allResults | Where-Object { $_.Status -eq "Failed" }
        
        if ($failures.Count -gt 0) {
            $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $errorFile = Join-Path $errorDir "$OperationType-errors_$timestamp.csv"
            
            $failures | ForEach-Object {
                [PSCustomObject]@{
                    FileName = if ($_.FileName) { $_.FileName } else { "Unknown" }
                    LocalPath = if ($_.LocalPath) { $_.LocalPath } else { "N/A" }
                    VcUrl = if ($_.VcUrl) { $_.VcUrl } else { if ($_.DestinationUrl) { $_.DestinationUrl } else { "N/A" } }
                    RelativePath = if ($_.RelativePath) { $_.RelativePath } else { if ($_.Path) { $_.Path } else { "N/A" } }
                    Size = if ($_.Size) { $_.Size } else { "0 MB" }
                    Status = $_.Status
                    Details = if ($_.Details) { $_.Details } else { "No error details" }
                    Time = if ($_.Time) { $_.Time } else { "0s" }
                    CreationTime = if ($_.CreationDate) { $_.CreationDate } else { if ($_.CreationTime) { $_.CreationTime } else { "Unknown" } }
                }
            } | Export-Csv -Path $errorFile -NoTypeInformation -Encoding UTF8
            
            Write-Log -Message "$OperationType error file saved: $errorFile ($($failures.Count) failed files)" -Level "INFO" -Color Yellow
            
            # Also save retry file format
            $retryFile = Join-Path $errorDir "$OperationType-retry_$timestamp.csv"
            $failures | ForEach-Object {
                [PSCustomObject]@{
                    FileName = if ($_.FileName) { $_.FileName } else { "Unknown" }
                    VcUrl = if ($OperationType -eq "Upload") { "LOCAL_FILE" } else { if ($_.VcUrl) { $_.VcUrl } else { "N/A" } }
                    RelativePath = if ($_.RelativePath) { $_.RelativePath } else { if ($_.Path) { $_.Path } else { "N/A" } }
                    CreationTime = if ($_.CreationDate) { $_.CreationDate } else { if ($_.CreationTime) { $_.CreationTime } else { "Unknown" } }
                    Size = if ($_.Size) { $_.Size } else { "0 MB" }
                    OriginalError = if ($_.Details) { $_.Details } else { "No error details" }
                }
            } | Export-Csv -Path $retryFile -NoTypeInformation -Encoding UTF8
            
            Write-Log -Message "$OperationType retry file saved: $retryFile" -Level "INFO" -Color Yellow
            return $retryFile
        } else {
            Write-Log -Message "No failed $OperationType operations to save" -Level "INFO" -Color Green
            return $null
        }
    } catch {
        Write-Log -Message "Error saving $OperationType error files: $_" -Level "ERROR" -Color Red
        return $null
    }
}

# ================================================================================================
# FAILURE REPORTING FUNCTIONS (WORKS FOR BOTH UPLOAD AND DOWNLOAD)
# ================================================================================================

function Show-ManualFailureReport {
    param([string]$OperationType = "UPLOAD")
    
    # Handle both upload and download results
    $allResults = if ($OperationType -eq "UPLOAD") {
        @($global:UploadResults.ToArray())
    } else {
        @($global:DownloadResults.ToArray())
    }
    
    $recentFailures = $allResults | Where-Object { 
        $_.Status -eq "Failed" -and 
        $_.FileName -and 
        $_.Details
    } | Select-Object -Last 10  # Show last 10 failures
    
    if ($recentFailures.Count -gt 0) {
        Write-Host "`n" -ForegroundColor Yellow
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "$OperationType FAILURE REPORT - $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "Recent failures ($($recentFailures.Count) shown):" -ForegroundColor Yellow
        
        foreach ($failure in $recentFailures) {
            $shortError = if ($failure.Details.Length -gt 80) { 
                $failure.Details.Substring(0, 77) + "..." 
            } else { 
                $failure.Details 
            }
            Write-Host "  ✗ $($failure.FileName) - $shortError" -ForegroundColor Red
        }
        
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
    }
}

function Show-FinalFailureReport {
    param([string]$OperationType = "UPLOAD")
    
    # Handle both upload and download results
    $allResults = if ($OperationType -eq "UPLOAD") {
        @($global:UploadResults.ToArray())
    } else {
        @($global:DownloadResults.ToArray())
    }
    
    $allFailures = $allResults | Where-Object { $_.Status -eq "Failed" }
    
    if ($allFailures.Count -gt 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "FINAL $OperationType FAILURE SUMMARY" -ForegroundColor Red  
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "Total failures: $($allFailures.Count)" -ForegroundColor Yellow
        
        # Group failures by error type
        $errorGroups = $allFailures | Group-Object { 
            if ($_.Details -match "Access is denied|Access.*denied|Permission.*denied") { "Access Denied" }
            elseif ($_.Details -match "authentication|Authentication") { "Authentication Error" }
            elseif ($_.Details -match "not found|does not exist|Not found") { "File Not Found" }
            elseif ($_.Details -match "timeout|timed out|Timeout") { "Timeout" }
            elseif ($_.Details -match "Invalid command line argument") { "Command Syntax Error" }
            elseif ($_.Details -match "network|connection|Network") { "Network Error" }
            else { "Other Error" }
        }
        
        foreach ($group in $errorGroups) {
            Write-Host "  $($group.Name): $($group.Count) files" -ForegroundColor Yellow
        }
        
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
    }
}

# ================================================================================================
# HTML REPORT GENERATION FUNCTIONS
# ================================================================================================

function Generate-HTMLReport {
    param(
        [string]$ReportType,
        [array]$Results,
        [string]$CustomPath = ""
    )
    
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
        $utcTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $currentUser = $env:USERNAME
        
        if ($CustomPath) {
            $reportFile = $CustomPath
        } else {
            $reportFile = Join-Path $reportsDir "${ReportType}_Report_${timestamp}.html"
        }
        
        # HTML Header with styling
        $html = @"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Themis $ReportType Report - $timestamp</title>
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 20px; 
            background-color: #f5f7fa; 
            color: #333;
        }
        .header { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            color: white; 
            padding: 20px; 
            border-radius: 10px; 
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 { 
            margin: 0; 
            font-size: 28px; 
            font-weight: 300;
        }
        .header .subtitle { 
            margin: 5px 0 0 0; 
            opacity: 0.9; 
            font-size: 14px;
        }
        .section { 
            background: white; 
            padding: 20px; 
            margin-bottom: 20px; 
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .section h2 { 
            color: #4a5568; 
            border-bottom: 2px solid #e2e8f0; 
            padding-bottom: 10px;
            margin-top: 0;
        }
        .stats-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
            gap: 15px; 
            margin: 20px 0;
        }
        .stat-card { 
            background: #f7fafc; 
            padding: 15px; 
            border-radius: 8px; 
            text-align: center;
            border: 1px solid #e2e8f0;
        }
        .stat-number { 
            font-size: 24px; 
            font-weight: bold; 
            color: #2d3748;
        }
        .stat-label { 
            color: #718096; 
            font-size: 14px; 
            margin-top: 5px;
        }
        .success { color: #38a169; }
        .error { color: #e53e3e; }
        .warning { color: #d69e2e; }
        table { 
            width: 100%; 
            border-collapse: collapse; 
            margin-top: 15px;
            background: white;
        }
        th, td { 
            padding: 12px; 
            text-align: left; 
            border-bottom: 1px solid #e2e8f0;
        }
        th { 
            background-color: #f7fafc; 
            font-weight: 600; 
            color: #4a5568;
            position: sticky;
            top: 0;
        }
        tr:hover { 
            background-color: #f7fafc; 
        }
        .status-success { 
            background-color: #c6f6d5; 
            color: #22543d; 
            padding: 4px 8px; 
            border-radius: 4px; 
            font-size: 12px; 
            font-weight: bold;
        }
        .status-failed { 
            background-color: #fed7d7; 
            color: #742a2a; 
            padding: 4px 8px; 
            border-radius: 4px; 
            font-size: 12px; 
            font-weight: bold;
        }
        .status-skipped { 
            background-color: #feebc8; 
            color: #744210; 
            padding: 4px 8px; 
            border-radius: 4px; 
            font-size: 12px; 
            font-weight: bold;
        }
        .details-cell { 
            max-width: 300px; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            white-space: nowrap;
            cursor: pointer;
        }
        .details-cell:hover {
            background-color: #f0f4f8;
            white-space: normal;
            overflow: visible;
        }
        .url-cell { 
            max-width: 400px; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            white-space: nowrap;
            font-family: monospace;
            font-size: 11px;
        }
        .footer { 
            text-align: center; 
            color: #718096; 
            font-size: 12px; 
            margin-top: 30px;
            padding: 20px;
            border-top: 1px solid #e2e8f0;
        }
        .filter-controls {
            margin: 15px 0;
            padding: 15px;
            background: #f7fafc;
            border-radius: 8px;
        }
        .filter-controls input, .filter-controls select {
            margin: 5px;
            padding: 8px;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
        }
        .collapsible-error {
            cursor: pointer;
            user-select: none;
        }
        .collapsible-error:hover {
            background-color: #f0f4f8;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 Themis $ReportType Report</h1>
        <div class="subtitle">
            Generated: $utcTime UTC | User: $currentUser | Report Type: $ReportType
        </div>
    </div>
"@

        # Calculate statistics
        $totalFiles = $Results.Count
        $successCount = ($Results | Where-Object { $_.Status -eq "Success" }).Count
        $failedCount = ($Results | Where-Object { $_.Status -eq "Failed" }).Count
        $skippedCount = ($Results | Where-Object { $_.Status -eq "Skipped" }).Count
        
        $totalSize = 0
        $totalTime = 0
        foreach ($result in $Results) {
            if ($result.Size -and $result.Size -match "(\d+\.?\d*)\s*MB") {
                $totalSize += [double]$matches[1]
            }
            if ($result.Time -and $result.Time -match "(\d+\.?\d*)s") {
                $totalTime += [double]$matches[1]
            }
        }
        
        $successRate = if ($totalFiles -gt 0) { [math]::Round(($successCount / $totalFiles) * 100, 1) } else { 0 }
        
        # Statistics section
        $html += @"
    <div class="section">
        <h2>📊 $ReportType Statistics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">$totalFiles</div>
                <div class="stat-label">Total Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-number success">$successCount</div>
                <div class="stat-label">Successful</div>
            </div>
            <div class="stat-card">
                <div class="stat-number error">$failedCount</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-number warning">$skippedCount</div>
                <div class="stat-label">Skipped</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$([math]::Round($totalSize, 2)) MB</div>
                <div class="stat-label">Total Data Size</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$([math]::Round($totalTime, 1))s</div>
                <div class="stat-label">Total Time</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$successRate%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>
    </div>
"@

        # Results table
        if ($Results.Count -gt 0) {
            $html += @"
    <div class="section">
        <h2>📁 $ReportType Results</h2>
        <div class="filter-controls">
            <input type="text" id="fileFilter" placeholder="Filter by filename..." onkeyup="filterTable()">
            <select id="statusFilter" onchange="filterTable()">
                <option value="">All Status</option>
                <option value="Success">Success Only</option>
                <option value="Failed">Failed Only</option>
                <option value="Skipped">Skipped Only</option>
            </select>
        </div>
        <table id="resultsTable">
            <thead>
                <tr>
                    <th>📄 File Name</th>
                    <th>📊 Status</th>
                    <th>📏 Size</th>
                    <th>⏱️ Time</th>
                    <th>🔗 URL</th>
                    <th>📝 Details (Click to expand)</th>
                </tr>
            </thead>
            <tbody>
"@

            foreach ($result in $Results) {
                $statusClass = switch ($result.Status) {
                    "Success" { "status-success" }
                    "Failed" { "status-failed" }
                    "Skipped" { "status-skipped" }
                    default { "status-failed" }
                }
                
                $fileName = if ($result.FileName) { [System.Web.HttpUtility]::HtmlEncode($result.FileName) } else { "Unknown" }
                $status = if ($result.Status) { $result.Status } else { "Unknown" }
                $size = if ($result.Size) { $result.Size } else { "0 MB" }
                $time = if ($result.Time) { $result.Time } else { "0s" }
                $vcUrl = if ($result.VcUrl) { [System.Web.HttpUtility]::HtmlEncode($result.VcUrl) } else { "N/A" }
                $details = if ($result.Details) { [System.Web.HttpUtility]::HtmlEncode($result.Details) } else { "No details" }
                
                $html += @"
                <tr>
                    <td><strong>$fileName</strong></td>
                    <td><span class="$statusClass">$status</span></td>
                    <td>$size</td>
                    <td>$time</td>
                    <td class="url-cell" title="$vcUrl">$vcUrl</td>
                    <td class="details-cell collapsible-error" title="Click to expand full error">$details</td>
                </tr>
"@
            }

            $html += @"
            </tbody>
        </table>
    </div>
"@
        }

        # Add JavaScript for filtering and collapsible errors
        $html += @"
    <script>
        function filterTable() {
            const fileFilter = document.getElementById('fileFilter').value.toLowerCase();
            const statusFilter = document.getElementById('statusFilter').value;
            const table = document.getElementById('resultsTable');
            const tbody = table.getElementsByTagName('tbody')[0];
            const rows = tbody.getElementsByTagName('tr');
            
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const fileName = row.cells[0].textContent.toLowerCase();
                const status = row.cells[1].textContent.trim();
                
                const fileMatch = fileName.includes(fileFilter);
                const statusMatch = statusFilter === '' || status === statusFilter;
                
                if (fileMatch && statusMatch) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            }
        }
        
        // Add click handlers for collapsible errors
        document.addEventListener('DOMContentLoaded', function() {
            const errorCells = document.querySelectorAll('.collapsible-error');
            errorCells.forEach(cell => {
                cell.addEventListener('click', function() {
                    if (this.style.whiteSpace === 'normal') {
                        this.style.whiteSpace = 'nowrap';
                        this.style.overflow = 'hidden';
                    } else {
                        this.style.whiteSpace = 'normal';
                        this.style.overflow = 'visible';
                    }
                });
            });
        });
    </script>
"@

        # Footer
        $html += @"
    <div class="footer">
        <p>Generated by Themis File Management Script | $utcTime UTC</p>
        <p>Report saved to: $reportFile</p>
    </div>
</body>
</html>
"@

        # Write HTML to file
        $html | Out-File -FilePath $reportFile -Encoding UTF8
        
        Write-Log -Message "HTML report generated: $reportFile" -Level "SUCCESS" -Color Green
        return $reportFile
        
    } catch {
        Write-Log -Message "Error generating HTML report: $($_.Exception.Message)" -Level "ERROR" -Color Red
        return $null
    }
}

function Generate-PhaseReports {
    param([hashtable]$AllPhaseData = @{})
    
    try {
        # Generate download report if download results exist
        if ($global:DownloadResults -and $global:DownloadResults.Count -gt 0) {
            $downloadResults = @($global:DownloadResults.ToArray())
            $downloadReport = Generate-HTMLReport -ReportType "Download" -Results $downloadResults
            Write-Log -Message "Download report generated: $downloadReport" -Level "SUCCESS" -Color Green
        }
        
        # Generate upload report if upload results exist
        if ($global:UploadResults -and $global:UploadResults.Count -gt 0) {
            $uploadResults = @($global:UploadResults.ToArray())
            $uploadReport = Generate-HTMLReport -ReportType "Upload" -Results $uploadResults
            Write-Log -Message "Upload report generated: $uploadReport" -Level "SUCCESS" -Color Green
        }
        
        # Generate overall summary report
        $allResults = @()
        if ($global:DownloadResults) { $allResults += @($global:DownloadResults.ToArray()) }
        if ($global:UploadResults) { $allResults += @($global:UploadResults.ToArray()) }
        
        if ($allResults.Count -gt 0) {
            $summaryReport = Generate-HTMLReport -ReportType "Summary" -Results $allResults
            Write-Log -Message "Summary report generated: $summaryReport" -Level "SUCCESS" -Color Green
        }
        
    } catch {
        Write-Log -Message "Error generating phase reports: $_" -Level "ERROR" -Color Red
    }
}

# ================================================================================================
# GLOBAL VARIABLES INITIALIZATION
# ================================================================================================
# Initialize directories if not already done
if (-not $reportsDir) {
    $reportsDir = Join-Path $PSScriptRoot "Reports"
    if (-not (Test-Path $reportsDir)) {
        New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null
    }
}

if (-not $errorDir) {
    $errorDir = Join-Path $PSScriptRoot "Errors"  
    if (-not (Test-Path $errorDir)) {
        New-Item -ItemType Directory -Path $errorDir -Force | Out-Null
    }
}

# ✅ FIXED: Initialize global result collections as dynamic lists
if (-not $global:DownloadResults) {
    $global:DownloadResults = [System.Collections.Generic.List[PSObject]]::new()
}

if (-not $global:UploadResults) {
    $global:UploadResults = [System.Collections.Generic.List[PSObject]]::new()
}

# ✅ FIXED: Initialize PhaseSummaries as dynamic list, not fixed array
if (-not $global:PhaseSummaries) {
    $global:PhaseSummaries = [System.Collections.Generic.List[PSObject]]::new()
}

if (-not $global:PhaseResults) {
    $global:PhaseResults = @{}
}

if (-not $global:ScriptStart) {
    $global:ScriptStart = Get-Date
}

# ✅ NEW: Initialize other required global variables
if (-not $global:CleanupInProgress) {
    $global:CleanupInProgress = $false
}



# Ensure all required directories are defined
if (-not $reportsDir) { $script:reportsDir = Join-Path $PSScriptRoot "Reports" }
if (-not $errorDir) { $script:errorDir = Join-Path $PSScriptRoot "Errors" }
if (-not $listDir) { $script:listDir = Join-Path $PSScriptRoot "Lists" }
if (-not $localStagingDir) { $script:localStagingDir = Join-Path $PSScriptRoot "LocalStaging" }

# Create directories if they don't exist
@($reportsDir, $errorDir, $listDir, $localStagingDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}



# ================================================================================================
# GLOBAL RESULTS TRACKING FOR REPORTS
# ================================================================================================

if (-not $global:DownloadResults) {
    $global:DownloadResults = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
}

if (-not $global:UploadResults) {
    $global:UploadResults = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
}

if (-not $global:PhaseResults) {
    $global:PhaseResults = @{}
}

# ================================================================================================
# MSAL TOKEN MANAGEMENT
# ================================================================================================
$global:MSALToken = $null
$global:TokenFilePath = "Q:\temp\themis-aad_token.txt"
$global:TokenCreatedTime = $null
$global:TokenRefreshThreshold = 50

$MSALConfig = @{
    Scope = 'https://datalake.azure.net//user_impersonation'
    ClientId = '1950a258-227b-4e31-a9cf-717495945fc2'
    RedirectUri = 'urn:ietf:wg:oauth:2.0:oob'
    Authority = 'https://login.windows.net/common'
}



function Test-MSALModule {
    try {
        Import-Module MSAL.PS -ErrorAction Stop
        return $true
    } catch {
        Write-Log -Message "MSAL.PS module not found. Installing..." -Level "WARN" -Color Yellow
        try {
            Install-Module MSAL.PS -Force -AllowClobber -Scope CurrentUser
            Import-Module MSAL.PS
            Write-Log -Message "✓ MSAL.PS module installed successfully" -Level "SUCCESS" -Color Green
            return $true
        } catch {
            Write-Log -Message "✗ Failed to install MSAL.PS module: $_" -Level "ERROR" -Color Red
            return $false
        }
    }
}

function Get-FreshMSALToken {
    param([bool]$ForceRefresh = $false)
    
    if (-not $UseMSAL) {
        return $null
    }
    
    $needsRefresh = $ForceRefresh
    if ($global:TokenCreatedTime -and -not $ForceRefresh) {
        $tokenAge = (Get-Date) - $global:TokenCreatedTime
        $needsRefresh = $tokenAge.TotalMinutes -gt $global:TokenRefreshThreshold
        
        if ($needsRefresh) {
            Write-Log -Message "Token is $([math]::Round($tokenAge.TotalMinutes, 1)) minutes old - refreshing..." -Level "INFO" -Color Yellow
        } else {
            Write-DebugLog "Token is $([math]::Round($tokenAge.TotalMinutes, 1)) minutes old - still valid"
            return $global:MSALToken
        }
    }
    
    if ($needsRefresh -or -not $global:MSALToken) {
        try {
            Write-Log -Message "Getting new MSAL token..." -Level "INFO" -Color Yellow
            
            $tokenResult = Get-MSALToken -Scope $MSALConfig.Scope `
                                       -ClientId $MSALConfig.ClientId `
                                       -RedirectUri $MSALConfig.RedirectUri `
                                       -Authority $MSALConfig.Authority `
                                       -Interactive
            
            if ($tokenResult -and $tokenResult.AccessToken) {
                $global:MSALToken = $tokenResult
                $global:TokenCreatedTime = Get-Date
                
                $tokenResult.AccessToken | Out-File -Encoding ascii -FilePath $global:TokenFilePath -Force
                
                $expiryTime = $global:TokenCreatedTime.AddMinutes(60)
                Write-Log -Message "✓ New MSAL token obtained (expires: $($expiryTime.ToString('HH:mm:ss')))" -Level "SUCCESS" -Color Green
                
                return $global:MSALToken
            } else {
                Write-Log -Message "✗ Failed to obtain MSAL token" -Level "ERROR" -Color Red
                return $null
            }
        } catch {
            Write-Log -Message "✗ Error getting MSAL token: $_" -Level "ERROR" -Color Red
            return $null
        }
    }
    
    return $global:MSALToken
}

function Update-ScopeCommandWithMSAL {
    param([string]$Command)
    
    if (-not $UseMSAL) {
        return $Command
    }
    
    $token = Get-FreshMSALToken
    if (-not $token) {
        return $Command
    }
    
    $updatedCommand = $Command -replace "-on UseAadAuthentication -u $user", "-on UseAadAuthentication -SecureInfoFile `"$global:TokenFilePath`""
    $updatedCommand = $updatedCommand -replace "-on UseCachedCredentials -u $user", "-on UseAadAuthentication -SecureInfoFile `"$global:TokenFilePath`""
    
    Write-DebugLog "Updated command with MSAL token"
    return $updatedCommand
}

# ================================================================================================
# GLOBAL CLEANUP TRACKING
# ================================================================================================
$global:RunspacePools = @()
$global:ActiveJobs = @()
$global:CleanupInProgress = $false
$global:TokenMonitorJob = $null
$global:FailureTracker = $null
$global:LastFailureReport = Get-Date

function Cleanup-Resources {
    if ($global:CleanupInProgress) { return }
    $global:CleanupInProgress = $true
    
    Write-Host "`n========================================" -ForegroundColor Yellow
    Write-Host "CLEANUP INITIATED" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
    
    if ($global:TokenMonitorJob) {
        Write-Host "Stopping token monitor job..." -ForegroundColor Yellow
        Stop-Job $global:TokenMonitorJob -ErrorAction SilentlyContinue
        Remove-Job $global:TokenMonitorJob -ErrorAction SilentlyContinue
    }
    
    if ($UseMSAL -and (Test-Path $global:TokenFilePath)) {
        Write-Host "Cleaning up token file..." -ForegroundColor Yellow
        Remove-Item $global:TokenFilePath -Force -ErrorAction SilentlyContinue
    }
    
    if ($global:ActiveJobs.Count -gt 0) {
        Write-Host "Stopping $($global:ActiveJobs.Count) active jobs..." -ForegroundColor Yellow
        foreach ($job in $global:ActiveJobs) {
            try {
                if ($job.PowerShell) {
                    $job.PowerShell.Stop()
                    $job.PowerShell.Dispose()
                }
            } catch {
                Write-Host "  Error stopping job: $_" -ForegroundColor DarkRed
            }
        }
        $global:ActiveJobs.Clear()
    }
    
    if ($global:RunspacePools.Count -gt 0) {
        Write-Host "Disposing $($global:RunspacePools.Count) runspace pools..." -ForegroundColor Yellow
        foreach ($pool in $global:RunspacePools) {
            try {
                if ($pool -and $pool.RunspacePoolStateInfo.State -ne 'Closed') {
                    $pool.Close()
                    $pool.Dispose()
                }
            } catch {
                Write-Host "  Error disposing runspace pool: $_" -ForegroundColor DarkRed
            }
        }
        $global:RunspacePools.Clear()
    }
    
    $scopeProcesses = Get-Process -Name "scope" -ErrorAction SilentlyContinue
    if ($scopeProcesses) {
        Write-Host "Terminating $($scopeProcesses.Count) scope.exe processes..." -ForegroundColor Yellow
        $scopeProcesses | ForEach-Object {
            try {
                $_ | Stop-Process -Force -ErrorAction SilentlyContinue
            } catch {}
        }
    }
    
    Start-Sleep -Milliseconds 500
    $remainingScope = Get-Process -Name "scope" -ErrorAction SilentlyContinue
    if ($remainingScope) {
        & cmd /c "taskkill /f /im scope.exe 2>nul" | Out-Null
    }
    
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "CLEANUP COMPLETED" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    
    $global:CleanupInProgress = $false
}

trap {
    if (-not $global:CleanupInProgress) {
        Write-Host "`n[TRAP] Script terminated unexpectedly - cleaning up..." -ForegroundColor Red
        Cleanup-Resources
    }
    break
}

try {
    [Console]::TreatControlCAsInput = $false
    $null = [Console]::CancelKeyPress.Add({
        param($sender, $e)
        if (-not $global:CleanupInProgress) {
            $e.Cancel = $true
            Write-Host "`n[CTRL+C] Interrupt received - cleaning up resources..." -ForegroundColor Red
            Cleanup-Resources
            exit 1
        }
    })
} catch {}

# ================================================================================================
# CONFIGURATION
# ================================================================================================
$source_https = "https://cosmos08.osdinfra.net/cosmos/bingads.algo.adquality/shares/bingads.algo.rap2/Priam/ThemisINTL/"
$source_vc = "vc://cosmos08/bingads.algo.adquality/shares/bingads.algo.rap2/Priam/ThemisINTL/"

$destination_prod_base = "vc://cosmos08/bingads.algo.adquality/shares/bingads.algo.prod.rap2/shared/ThemisINTL/"
$destination_local_base = "vc://cosmos08/bingads.algo.adquality/local/users/vdamotharan/ThemisINTL/"

$destination_base = if ($DestinationType -eq "prod") { $destination_prod_base } else { $destination_local_base }

$localStagingDir = "Q:\temp\themis-staging"
$listDir = "Q:\temp\themis-listing"
$reportDir = "Q:\temp\themis-reports"
$errorDir = "Q:\temp\themis-errors"

$user = "vdamotharan@microsoft.com"
$expiry_days = "1"

$directoryConfigs = @(
    @{ Path = "Counts/Count7511/Aggregates/"; Type = "Count7511" },
    @{ Path = "Counts/Count7513/Aggregates/"; Type = "Count7513" },
    @{ Path = "Counts/Count7515/Aggregates/"; Type = "Count7515" },
    @{ Path = "PipelineRunState/"; Type = "PipelineRunState" },
    @{ Path = "V1/Daily/Monitor/"; Type = "V1Monitor" },
    @{ Path = "V2/Daily/Monitor/"; Type = "V2Monitor" },
    @{ Path = "V1/Daily/"; Type = "V1Daily"; ExcludePatterns = @("Monitor" ) },
    @{ Path = "V2/Daily/"; Type = "V2Daily"; ExcludePatterns = @("Monitor") }
)

@($localStagingDir, $listDir, $reportDir, $errorDir) | ForEach-Object {
    if (!(Test-Path $_)) { 
        New-Item -ItemType Directory -Path $_ -Force | Out-Null 
    }
}

# ================================================================================================
# GLOBALS
# ================================================================================================
$global:ScriptStart = Get-Date
$global:PhaseSummaries = @()
$global:DownloadResults = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
$global:UploadResults = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
$global:ErrorFiles = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()

# ================================================================================================
# UTILITY FUNCTIONS
# ================================================================================================
function Parse-FileTypes {
    param([string]$FileTypeString)
    
    if ($RetryMode) {
        $allTypes = $directoryConfigs | ForEach-Object { $_.Type }
        Write-Log -Message "RETRY MODE: Ignoring file type filters - processing all types: $($allTypes -join ', ')" -Level "INFO" -Color Magenta
        return $allTypes
    }
    
    if ($FileTypeString -eq "all") {
        $allTypes = $directoryConfigs | ForEach-Object { $_.Type }
        Write-Log -Message "FileType 'all' specified - including all types: $($allTypes -join ', ')" -Level "INFO" -Color Cyan
        return $allTypes
    } else {
        $types = $FileTypeString -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
        Write-Log -Message "FileType specified: $($types -join ', ')" -Level "INFO" -Color Cyan
        
        $validTypes = $directoryConfigs | ForEach-Object { $_.Type }
        $invalidTypes = $types | Where-Object { $_ -notin $validTypes }
        
        if ($invalidTypes.Count -gt 0) {
            Write-Log -Message "Invalid file types detected: $($invalidTypes -join ', ')" -Level "WARN" -Color Yellow
            Write-Log -Message "Valid file types are: $($validTypes -join ', ')" -Level "INFO" -Color Yellow
        }
        
        $validRequestedTypes = $types | Where-Object { $_ -in $validTypes }
        if ($validRequestedTypes.Count -eq 0) {
            Write-Log -Message "No valid file types specified! Using all types." -Level "WARN" -Color Yellow
            return $validTypes
        }
        
        return $validRequestedTypes
    }
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO", [ConsoleColor]$Color = [ConsoleColor]::Gray)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff")
    Write-Host "[$ts][$Level] $Message" -ForegroundColor $Color
}

function Write-DebugLog {
    param([string]$Message)
    if ($DebugMode) { Write-Log -Message $Message -Level "DEBUG" -Color DarkCyan }
}

function Show-ProgressBar {
    param(
        [int]$Current, 
        [int]$Total, 
        [string]$Activity, 
        [datetime]$StartTime, 
        [int]$SuccessCount = 0, 
        [int]$FailCount = 0,
        [switch]$RetryMode = $false
    )
    
    if ($Total -eq 0) { return }
    
    $percentComplete = [math]::Round(($Current / $Total) * 100, 2)
    $elapsed = (Get-Date) - $StartTime
    $elapsedSeconds = $elapsed.TotalSeconds
    
    # ENHANCED ETA CALCULATION WITH MULTIPLE STRATEGIES
    $etaString = "ETA: Calculating..."
    
    if ($Current -gt 2 -and $elapsedSeconds -gt 3) {  # Need at least 3 completed items and 3 seconds
        
        # Strategy 1: Use successful completions if we have enough data
        if ($SuccessCount -ge 2) {
            $avgTimePerSuccess = $elapsedSeconds / $SuccessCount
            $remainingItems = $Total - $Current
            $currentSuccessRate = [math]::Max($SuccessCount / $Current, 0.1)  # Minimum 10% assumed success rate
            $estimatedRemainingSuccesses = $remainingItems * $currentSuccessRate
            $etaSeconds = $avgTimePerSuccess * $estimatedRemainingSuccesses
            
        # Strategy 2: Use overall completion rate if no successes yet
        } else {
            $avgTimePerItem = $elapsedSeconds / $Current
            $remainingItems = $Total - $Current
            $etaSeconds = $avgTimePerItem * $remainingItems
        }
        
        # Format ETA based on time range
        if ($etaSeconds -gt 0) {
            if ($etaSeconds -lt 60) {
                $etaString = "ETA: {0}s" -f [math]::Round($etaSeconds)
            } elseif ($etaSeconds -lt 3600) {
                $minutes = [math]::Round($etaSeconds / 60)
                $etaString = "ETA: {0}m" -f $minutes
            } elseif ($etaSeconds -lt 86400) {
                $hours = [math]::Floor($etaSeconds / 3600)
                $minutes = [math]::Round(($etaSeconds % 3600) / 60)
                $etaString = "ETA: {0}h {1}m" -f $hours, $minutes
            } else {
                $etaString = "ETA: >24h"
            }
        }
        
    } elseif ($elapsedSeconds -le 3) {
        $etaString = "ETA: Starting..."
    } elseif ($Current -le 2) {
        $etaString = "ETA: Analyzing..."
    }
    
    # Calculate rates and statistics
    $successRate = if ($Current -gt 0) { [math]::Round(($SuccessCount / $Current) * 100, 1) } else { 0 }
    $itemsPerSecond = if ($elapsedSeconds -gt 0) { [math]::Round($Current / $elapsedSeconds, 1) } else { 0 }
    
    # Progress bar visualization with color coding
    $barLength = 50
    $filledLength = [math]::Round(($percentComplete / 100) * $barLength)
    
    # Color-code the progress bar based on success rate
    $barColor = if ($successRate -ge 80) { "Green" } 
               elseif ($successRate -ge 50) { "Yellow" } 
               else { "Cyan" }
    
    $bar = "█" * $filledLength + "░" * ($barLength - $filledLength)
    
    # Activity text with mode indicators
    $modeIndicator = if ($RetryMode) { " (RETRY)" } else { "" }
    $activityText = "$Activity$modeIndicator"
    
    # Build comprehensive progress string
    $progressText = "$activityText [$bar] $percentComplete% | $Current/$Total | ✓$SuccessCount ✗$FailCount | Success: $successRate% | Rate: $itemsPerSecond/s | Elapsed: $($elapsed.ToString('hh\:mm\:ss')) | $etaString"
    
    # Use color based on success rate
    $textColor = if ($successRate -ge 80) { "Green" } 
                elseif ($successRate -ge 50) { "Cyan" } 
                elseif ($successRate -ge 20) { "Yellow" } 
                else { "Red" }
    
    Write-Host "`r$progressText" -NoNewline -ForegroundColor $textColor
}

function Show-ManualFailureReport {
    param([string]$OperationType = "DOWNLOAD")
    
    $currentFailures = @()
    $allResults = @($global:DownloadResults.ToArray())
    $recentFailures = $allResults | Where-Object { 
        $_.Status -eq "Failed" -and 
        $_.FileName -and 
        $_.Details
    } | Select-Object -Last 10  # Show last 10 failures
    
    if ($recentFailures.Count -gt 0) {
        Write-Host "`n" -ForegroundColor Yellow
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "$OperationType FAILURE REPORT - $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "Recent failures ($($recentFailures.Count) shown):" -ForegroundColor Yellow
        
        foreach ($failure in $recentFailures) {
            $shortError = if ($failure.Details.Length -gt 80) { 
                $failure.Details.Substring(0, 77) + "..." 
            } else { 
                $failure.Details 
            }
            Write-Host "  ✗ $($failure.FileName) - $shortError" -ForegroundColor Red
        }
        
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
    }
}

# ================================================================================================
# FAILURE MONITORING
# ================================================================================================
function Start-FailureMonitoring {
    param(
        [string]$OperationType = "Operation",
        [int]$ReportIntervalMinutes = 5
    )
    
    $failureMonitorJob = Start-Job -ScriptBlock {
        param($reportInterval, $opType, $isRetryMode)
        
        $lastReportTime = Get-Date
        
        while ($true) {
            Start-Sleep -Seconds 30
            
            $now = Get-Date
            
            if (($now - $lastReportTime).TotalMinutes -ge $reportInterval) {
                $failures = @()
                
                $queue = [System.Collections.Concurrent.ConcurrentQueue[PSObject]]$using:global:FailureTracker
                
                if ($queue) {
                    $failure = $null
                    while ($queue.TryDequeue([ref]$failure)) {
                        $failures += $failure
                    }
                }
                
                if ($failures.Count -gt 0) {
                    $retryText = if ($isRetryMode) { " (RETRY MODE)" } else { "" }
                    Write-Host "`n" -ForegroundColor Yellow
                    Write-Host "========================================" -ForegroundColor Red
                    Write-Host "$opType FAILURE REPORT$retryText - $($now.ToString('HH:mm:ss'))" -ForegroundColor Red
                    Write-Host "========================================" -ForegroundColor Red
                    Write-Host "Recent failures ($($failures.Count) files):" -ForegroundColor Yellow
                    
                    $failures | Sort-Object Time | ForEach-Object {
                        $shortError = if ($_.Details.Length -gt 80) { 
                            $_.Details.Substring(0, 77) + "..." 
                        } else { 
                            $_.Details 
                        }
                        Write-Host "  ✗ $($_.FileName) - $shortError" -ForegroundColor Red
                    }
                    
                    Write-Host "========================================" -ForegroundColor Red
                    Write-Host ""
                }
                
                $lastReportTime = $now
            }
        }
    } -ArgumentList $ReportIntervalMinutes, $OperationType, $RetryMode
    
    return $failureMonitorJob
}

function Show-FinalFailureReport {
    param([string]$OperationType = "Operation")
    
    $finalFailures = @()
    
    if ($global:FailureTracker) {
        $failure = $null
        while ($global:FailureTracker.TryDequeue([ref]$failure)) {
            $finalFailures += $failure
        }
    }
    
    if ($finalFailures.Count -gt 0) {
        $retryText = if ($RetryMode) { " (RETRY MODE)" } else { "" }
        Write-Host "`n" -ForegroundColor Yellow
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "FINAL $OperationType FAILURE SUMMARY$retryText" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "Total failed files: $($finalFailures.Count)" -ForegroundColor Yellow
        
        $groupedFailures = $finalFailures | Group-Object { 
            if ($_.Details -like "*Authentication*") { "Authentication" }
            elseif ($_.Details -like "*Not found*") { "Not Found" }
            elseif ($_.Details -like "*Access denied*") { "Access Denied" }
            elseif ($_.Details -like "*Timeout*") { "Timeout" }
            elseif ($_.Details -like "*Permission*") { "Permission" }
            elseif ($_.Details -like "*Quota*") { "Quota" }
            else { "Other" }
        }
        
        foreach ($group in $groupedFailures) {
            Write-Host "`n$($group.Name) errors ($($group.Count) files):" -ForegroundColor Cyan
            $group.Group | Select-Object -First 3 | ForEach-Object {
                $shortError = if ($_.Details.Length -gt 60) { 
                    $_.Details.Substring(0, 57) + "..." 
                } else { 
                    $_.Details 
                }
                Write-Host "  ✗ $($_.FileName) - $shortError" -ForegroundColor Red
            }
            if ($group.Count -gt 3) {
                Write-Host "  ... and $($group.Count - 3) more files" -ForegroundColor DarkRed
            }
        }
        Write-Host "========================================" -ForegroundColor Red
    }
}

function Save-ErrorFiles {
    param(
        [string]$OperationType,
        [array]$Results
    )
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $errorFileName = "$errorDir\$OperationType`_Errors_$timestamp.txt"
    
    $failedFiles = $Results | Where-Object { $_.Status -eq "Failed" }
    
    if ($failedFiles.Count -gt 0) {
        Write-Log -Message "Saving $($failedFiles.Count) failed files to error file..." -Level "INFO" -Color Yellow
        
        $errorContent = @()
        $errorContent += "# THEMIS $OperationType ERROR FILE"
        $errorContent += "# Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC')"
        $errorContent += "# User: $user"
        $errorContent += "# Total Failed Files: $($failedFiles.Count)"
        $errorContent += "# Format: VcUrl|FileName|RelativePath|Extension|CreationTime|Size|LastModified|ErrorDetails"
        $errorContent += "#"
        
        foreach ($failedFile in $failedFiles) {
            if ($OperationType -eq "Download") {
                $errorLine = "$($failedFile.VcUrl)|$($failedFile.FileName)|$($failedFile.Path)|Unknown|Unknown|$($failedFile.Size)|Unknown|$($failedFile.Details)"
            } else {
                $errorLine = "LOCAL_FILE|$($failedFile.FileName)|$($failedFile.Path)|Unknown|Unknown|$($failedFile.Size)|Unknown|$($failedFile.Details)"
            }
            $errorContent += $errorLine
        }
        
        $errorContent | Out-File -FilePath $errorFileName -Encoding UTF8
        
        Write-Log -Message "Error file saved: $errorFileName" -Level "SUCCESS" -Color Green
        Write-Log -Message "To retry failed files, use: -ErrorFile `"$errorFileName`" -RetryMode" -Level "INFO" -Color Cyan
        
        return $errorFileName
    } else {
        Write-Log -Message "No failed files to save" -Level "INFO" -Color Green
        return $null
    }
}

function Load-ErrorFileForRetry {
    param([string]$ErrorFilePath)
    
    if (-not (Test-Path $ErrorFilePath)) {
        Write-Log -Message "Error file not found: $ErrorFilePath" -Level "ERROR" -Color Red
        return @()
    }
    
    Write-Log -Message "Loading error file for retry: $ErrorFilePath" -Level "INFO" -Color Yellow
    
    $retryFiles = @()
    $lines = Get-Content $ErrorFilePath | Where-Object { -not $_.StartsWith("#") -and $_.Trim() -ne "" }
    
    foreach ($line in $lines) {
        $parts = $line -split "\|"
        if ($parts.Length -ge 4) {
            $retryFiles += [PSCustomObject]@{
                VcUrl = $parts[0].Trim()
                FileName = $parts[1].Trim()
                RelativePath = $parts[2].Trim()
                Extension = $parts[3].Trim()
                CreationTime = if ($parts.Length -ge 5) { $parts[4].Trim() } else { "Unknown" }
                Size = if ($parts.Length -ge 6) { $parts[5].Trim() } else { "Unknown" }
                LastModified = if ($parts.Length -ge 7) { $parts[6].Trim() } else { "Unknown" }
                OriginalError = if ($parts.Length -ge 8) { $parts[7].Trim() } else { "Unknown" }
            }
        }
    }
    
    Write-Log -Message "Loaded $($retryFiles.Count) files for retry" -Level "SUCCESS" -Color Green
    return $retryFiles
}

function Invoke-ScopeCommand {
    param(
        [string]$Command,
        [string]$Operation = "operation"
    )
    
    if ($global:CleanupInProgress) {
        Write-DebugLog "Cleanup in progress, aborting operation"
        return @{ Success = $false; Output = "Cleanup in progress"; UsedAuth = $false }
    }
    
    # MSAL TOKEN APPROACH
    if ($UseMSAL) {
        Write-DebugLog "Using MSAL token authentication"
        $msalCommand = Update-ScopeCommandWithMSAL -Command $Command
        
        try {
            $result = Invoke-Expression $msalCommand 2>&1
            $exitCode = $LASTEXITCODE
            
            if ($exitCode -eq 0) {
                Write-DebugLog "✓ Success with MSAL token"
                return @{ Success = $true; Output = $result; UsedAuth = $true }
            } else {
                Write-Log -Message "MSAL token failed, attempting refresh..." -Level "WARN" -Color Yellow
                $refreshedToken = Get-FreshMSALToken -ForceRefresh $true
                
                if ($refreshedToken) {
                    $msalCommand = Update-ScopeCommandWithMSAL -Command $Command
                    $result = Invoke-Expression $msalCommand 2>&1
                    $exitCode = $LASTEXITCODE
                    
                    if ($exitCode -eq 0) {
                        Write-Log -Message "✓ Success with refreshed MSAL token" -Level "SUCCESS" -Color Green
                        return @{ Success = $true; Output = $result; UsedAuth = $true }
                    }
                }
                
                Write-Log -Message "✗ MSAL token authentication failed, falling back to standard auth" -Level "WARN" -Color Yellow
            }
        } catch {
            Write-Log -Message "Exception with MSAL token: $_, falling back to standard auth" -Level "WARN" -Color Yellow
        }
    }
    
    # FALLBACK AUTHENTICATION
    $noAuthCommand = $Command -replace "-on UseAadAuthentication -u $user", ""
    $noAuthCommand = $noAuthCommand -replace "-SecureInfoFile `"[^`"]+`"", ""
    Write-DebugLog "Trying without auth: $noAuthCommand"
    
    try {
        $result = Invoke-Expression $noAuthCommand 2>&1
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-DebugLog "✓ Success without auth"
            return @{ Success = $true; Output = $result; UsedAuth = $false }
        }
    } catch {}
    
    $cachedCommand = $Command -replace "-on UseAadAuthentication", "-on UseCachedCredentials"
    $cachedCommand = $cachedCommand -replace "-SecureInfoFile `"[^`"]+`"", ""
    Write-DebugLog "Trying with cached credentials"
    
    try {
        $result = Invoke-Expression $cachedCommand 2>&1
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-DebugLog "✓ Success with cached credentials"
            return @{ Success = $true; Output = $result; UsedAuth = $false }
        }
    } catch {}
    
    Write-Log -Message "Using interactive AAD authentication for $Operation..." -Level "AUTH" -Color Yellow
    
    try {
        $result = Invoke-Expression $Command 2>&1
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Log -Message "✓ Success with interactive AAD authentication" -Level "SUCCESS" -Color Green
            return @{ Success = $true; Output = $result; UsedAuth = $true }
        } else {
            Write-Log -Message "✗ Failed even with interactive AAD authentication" -Level "ERROR" -Color Red
            return @{ Success = $false; Output = $result; UsedAuth = $true }
        }
    } catch {
        Write-Log -Message "Exception during authentication: $_" -Level "ERROR" -Color Red
        return @{ Success = $false; Output = $_.Exception.Message; UsedAuth = $true }
    }
}

function Start-Phase {
    param([string]$Name)
    $phaseText = if ($RetryMode) { "$Name (RETRY)" } else { $Name }
    Write-Log -Message "==== START PHASE: $phaseText ====" -Level "PHASE" -Color Cyan
    [PSCustomObject]@{ Name = $phaseText; Start = Get-Date }
}

function End-Phase {
    param([PSCustomObject]$PhaseRef, [hashtable]$Data)
    $end = Get-Date
    $elapsed = New-TimeSpan -Start $PhaseRef.Start -End $end
    Write-Log -Message ("==== END PHASE: {0} | Duration: {1:hh\:mm\:ss\.fff} ====" -f $PhaseRef.Name,$elapsed) -Level "PHASE" -Color Cyan
    $summary = [PSCustomObject]@{ Phase = $PhaseRef.Name; Duration = $elapsed; Data = $Data }
    $global:PhaseSummaries += $summary
}

# ================================================================================================
# THEMIS FILE MANAGEMENT SCRIPT - COMPLETE WITHOUT METADATA - PART 2
# Current Date and Time (UTC): 2025-08-12 05:11:48
# Current User: varadharajaan
# ================================================================================================

# ================================================================================================
# PHASE 1: SIMPLE LISTING WITHOUT METADATA
# ================================================================================================
function Phase1-ListAllFiles {
    if ($RetryMode) {
        Write-Log -Message "Phase 1 SKIPPED: Retry mode active - using error file instead" -Level "INFO" -Color Magenta
        return
    }
    
    $phaseRef = Start-Phase -Name "Phase1-ListAllFiles-Simple"
    $totalListed = 0
    
    Write-Log -Message "Phase 1: Simple recursive listing (NO METADATA EXTRACTION)" -Level "INFO" -Color Yellow
    Write-Log -Message "Source: $source_https" -Level "INFO" -Color Cyan
    Write-Log -Message "Output: $listDir" -Level "INFO" -Color Cyan
    
    $fileTypeFilters = Parse-FileTypes -FileTypeString $FileType
    Write-Log -Message "Processing file types: $($fileTypeFilters -join ', ')" -Level "INFO" -Color Green
    
    try {
        Write-Log -Message "Executing single recursive directory listing..." -Level "INFO" -Color Yellow
        
        $command = "scope.exe dir `"$source_https`" -recursive -on UseAadAuthentication -u $user"
        $commandResult = Invoke-ScopeCommand -Command $command -Operation "directory listing"
        
        if (-not $commandResult.Success) {
            Write-Log -Message "Failed to list directory" -Level "ERROR" -Color Red
            End-Phase -PhaseRef $phaseRef -Data @{ TotalListed = 0; Error = "Directory listing failed" }
            return
        }
        
        $result = $commandResult.Output
        Write-Log -Message "✓ Directory listing completed" -Level "SUCCESS" -Color Green
        
        # Initialize file collections
        $filesByType = @{}
        foreach ($config in $directoryConfigs) {
            $filesByType[$config.Type] = @()
        }
        
        Write-Log -Message "Parsing directory output (without metadata)..." -Level "INFO" -Color Yellow
        
        # Parse results
        $lines = $result -split "`n"
        $parseStartTime = Get-Date
        $lineCount = $lines.Count
        $processedLines = 0
        
        foreach ($line in $lines) {
            if ($global:CleanupInProgress) { break }
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            
            $processedLines++
            
            if ($processedLines % 100 -eq 0) {
                Show-ProgressBar -Current $processedLines -Total $lineCount -Activity "Parsing listing" -StartTime $parseStartTime
            }
            
            if ($line -match "^Stream\s*:\s*(https://cosmos08\.osdinfra\.net(?::443)?/cosmos/.*?/)([^/\s]+)\s*$") {
                $fullUrl = $matches[1] + $matches[2]
                $fileName = $matches[2].Trim()
                
                Write-DebugLog "Found file: $fileName"
                
                $cleanUrl = $fullUrl -replace ":443", ""
                
                $sortedConfigs = $directoryConfigs | Sort-Object { $_.Path.Length } -Descending
                
                $fileMatched = $false
                foreach ($config in $sortedConfigs) {
                    if ($fileMatched) { break }
                    
                    $expectedPath = $source_https + $config.Path
                    
                    if ($cleanUrl.StartsWith($expectedPath)) {
                        $shouldExclude = $false
                        if ($config.ExcludePatterns) {
                            foreach ($excludePattern in $config.ExcludePatterns) {
                                $pathAfterBase = $cleanUrl.Substring($expectedPath.Length)
                                if ($pathAfterBase -match "^$excludePattern/" -or $pathAfterBase -match "/$excludePattern/") {
                                    $shouldExclude = $true
                                    Write-DebugLog "Excluded by pattern '$excludePattern': $fileName (Path: $pathAfterBase)"
                                    break
                                }
                            }
                        }
                        
                        if ($shouldExclude) { continue }
                        
                        if ($fileTypeFilters -notcontains $config.Type) {
                            Write-DebugLog "Filtered by type: $fileName (Type: $($config.Type), Requested: $($fileTypeFilters -join ','))"
                            continue
                        }
                        
                        $fullPathVc = $cleanUrl -replace "https://cosmos08\.osdinfra\.net/cosmos/", "vc://cosmos08/"
                        $extension = [System.IO.Path]::GetExtension($fileName).ToLower()
                        
                        # Create file entry WITHOUT metadata
                        $fileInfo = [PSCustomObject]@{
                            FileName = $fileName
                            HttpsUrl = $cleanUrl
                            VcUrl = $fullPathVc
                            RelativePath = $config.Path
                            Extension = $extension
                            CreationTime = "Unknown"  # No metadata extraction
                            Size = "Unknown"          # No metadata extraction
                            LastModified = "Unknown"  # No metadata extraction
                        }
                        
                        $filesByType[$config.Type] += $fileInfo
                        $totalListed++
                        $fileMatched = $true
                        
                        Write-DebugLog "Added to $($config.Type): $fileName (no metadata)"
                    }
                }
            }
        }
        
        Write-Host ""
        Write-Log -Message "✓ Categorized $totalListed files (without metadata)" -Level "SUCCESS" -Color Green
        
        foreach ($config in $directoryConfigs) {
            $count = $filesByType[$config.Type].Count
            if ($count -gt 0) {
                Write-Log -Message "  $($config.Type): $count files" -Level "INFO" -Color DarkGreen
            }
        }
        
        # Create output files
        foreach ($config in $directoryConfigs) {
            if ($global:CleanupInProgress) { break }
            
            $files = $filesByType[$config.Type]
            
            if ($files.Count -eq 0) { 
                Write-DebugLog "No files found for type: $($config.Type)"
                continue 
            }
            
            Write-Log -Message "Creating lists for $($config.Type): $($files.Count) files" -Level "SUCCESS" -Color Green
            
            $httpsListAll = "$listDir\$($config.Type)_https_listall.txt"
            $vcListAll = "$listDir\$($config.Type)_vc_listall.txt"
            $httpsSimple = "$listDir\$($config.Type)_https_listall_simple.txt"
            $vcSimple = "$listDir\$($config.Type)_vc_listall_simple.txt"
            
            # Create detailed lists (with placeholders for metadata)
            $httpsDetailed = $files | ForEach-Object {
                "$($_.HttpsUrl)|$($_.FileName)|$($_.RelativePath)|$($_.Extension)|$($_.CreationTime)|$($_.Size)|$($_.LastModified)"
            }
            $httpsDetailed | Out-File -FilePath $httpsListAll -Encoding UTF8
            
            $vcDetailed = $files | ForEach-Object {
                "$($_.VcUrl)|$($_.FileName)|$($_.RelativePath)|$($_.Extension)|$($_.CreationTime)|$($_.Size)|$($_.LastModified)"
            }
            $vcDetailed | Out-File -FilePath $vcListAll -Encoding UTF8
            
            # Create simple lists
            $files | ForEach-Object { $_.HttpsUrl } | Out-File -FilePath $httpsSimple -Encoding UTF8
            $files | ForEach-Object { $_.VcUrl } | Out-File -FilePath $vcSimple -Encoding UTF8
            
            Write-Log -Message "  ✓ Lists saved for $($config.Type)" -Level "INFO" -Color DarkGreen
        }
        
        End-Phase -PhaseRef $phaseRef -Data @{ TotalListed = $totalListed }
        Write-Log -Message "Phase 1 COMPLETED: $totalListed files listed (without metadata)" -Level "SUCCESS" -Color Green
        
    } catch {
        Write-Log -Message "Error in Phase 1: $_" -Level "ERROR" -Color Red
        End-Phase -PhaseRef $phaseRef -Data @{ TotalListed = $totalListed; Error = $_.Exception.Message }
    }
}

# ================================================================================================
# PHASE 2: DOWNLOAD WITH SIMPLE DATE FILTERING
# ================================================================================================

function Phase2-DownloadToLocal {
    param([hashtable]$PhaseData = @{})
    
    $phaseStart = Get-Date
    Write-Log -Message "==== START PHASE: Phase2-DownloadToLocal ====" -Level "PHASE" -Color Magenta
    
    try {
        # Set destination and user
        $user = "varadharajaan@microsoft.com"
        Write-Log -Message "Phase 2: Parallel Download from Cosmos source" -Level "INFO" -Color Green
        Write-Log -Message "Max Threads: $MaxThreads" -Level "INFO" -Color Cyan
        Write-Log -Message "Destination: $localStagingDir" -Level "INFO" -Color Cyan
        Write-Log -Message "User: $user" -Level "INFO" -Color Cyan
        
        # Initialize counters
        $downloaded = 0
        $failed = 0
        $skipped = 0
        
        $allDownloads = @()
        
        # ✅ RETRY MODE LOGIC FOR DOWNLOADS
        if ($RetryMode -and -not [string]::IsNullOrEmpty($ErrorFile)) {
            Write-Log -Message "RETRY MODE: Loading files from error file..." -Level "INFO" -Color Magenta
            
            try {
                if (-not (Test-Path $ErrorFile)) {
                    Write-Log -Message "Error file not found: $ErrorFile" -Level "ERROR" -Color Red
                    return @{ Downloaded = 0; Failed = 1; Skipped = 0; Error = "Error file not found" }
                }
                
                $retryFiles = Import-Csv -Path $ErrorFile
                Write-Log -Message "Loaded $($retryFiles.Count) entries from error file" -Level "INFO" -Color Green
                
                foreach ($retryFile in $retryFiles) {
                    # Validate required fields
                    if (-not $retryFile.FileName -or -not $retryFile.VcUrl) {
                        Write-Log -Message "  Skipping invalid entry: missing FileName or VcUrl" -Level "WARN" -Color Yellow
                        continue
                    }
                    
                    # Determine local path for retry
                    $localFilePath = ""
                    if ($retryFile.LocalPath -and $retryFile.LocalPath -ne "N/A") {
                        $localFilePath = $retryFile.LocalPath
                    } else {
                        # Reconstruct local path based on relative path
                        $relativePath = if ($retryFile.RelativePath) { $retryFile.RelativePath.Trim('/') } else { "Counts/Count7511/Aggregates" }
                        $localFilePath = Join-Path $localStagingDir $relativePath
                        $localFilePath = Join-Path $localFilePath $retryFile.FileName
                    }
                    
                    # Ensure directory exists
                    $localDir = Split-Path $localFilePath -Parent
                    if (-not (Test-Path $localDir)) {
                        New-Item -ItemType Directory -Path $localDir -Force | Out-Null
                    }
                    
                    $allDownloads += [PSCustomObject]@{
                        FileName = $retryFile.FileName
                        VcUrl = $retryFile.VcUrl
                        LocalPath = $localFilePath
                        RelativePath = if ($retryFile.RelativePath) { $retryFile.RelativePath } else { "Counts/Count7511/Aggregates/" }
                        CreationTime = if ($retryFile.CreationTime) { $retryFile.CreationTime } else { "Unknown" }
                        Status = $null
                        Size = $null
                        Time = $null
                        Details = $null
                        OriginalError = if ($retryFile.OriginalError) { $retryFile.OriginalError } else { $retryFile.Details }
                    }
                    
                    Write-Log -Message "  Queued for retry: $($retryFile.FileName)" -Level "DEBUG" -Color DarkGray
                }
                
                Write-Log -Message "RETRY MODE: Loaded $($allDownloads.Count) files for retry download" -Level "SUCCESS" -Color Green
                
            } catch {
                Write-Log -Message "Error loading retry file: $($_.Exception.Message)" -Level "ERROR" -Color Red
                return @{ Downloaded = 0; Failed = 1; Skipped = 0; Error = "Error loading retry file" }
            }
            
        } else {
            # ✅ NORMAL MODE: Use input file or scan Cosmos
            Write-Log -Message "NORMAL MODE: Processing file list..." -Level "INFO" -Color Green
            
            # Apply DaysBack filtering
            if ($DaysBack -and $DaysBack -gt 0) {
                Write-Log -Message "DaysBack filtering: ENABLED - only files from last $DaysBack days" -Level "INFO" -Color Yellow
            } else {
                Write-Log -Message "DaysBack filtering: DISABLED - downloading all files" -Level "INFO" -Color Green
            }
            
            # Parse FileType
            $fileTypeFilters = Parse-FileTypes -FileTypeString $FileType
            Write-Log -Message "FileType specified: $($fileTypeFilters -join ',')" -Level "INFO" -Color Cyan
            
            # Load file list
            $inputData = @()
            if (-not [string]::IsNullOrEmpty($InputFile) -and (Test-Path $InputFile)) {
                Write-Log -Message "Loading file list from: $InputFile" -Level "INFO" -Color Cyan
                $inputData = Import-Csv -Path $InputFile
                Write-Log -Message "Loaded $($inputData.Count) entries from input file" -Level "SUCCESS" -Color Green
            } else {
                Write-Log -Message "No input file specified. Use Phase 1 to generate file list first." -Level "ERROR" -Color Red
                return @{ Downloaded = 0; Failed = 1; Skipped = 0; Error = "No input file specified" }
            }
            
            # Filter and process input data
            foreach ($item in $inputData) {
                if (-not $item.FileName -or -not $item.VcUrl) { continue }
                
                # Apply FileType filtering
                $matchesFileType = $false
                foreach ($filterType in $fileTypeFilters) {
                    if ($item.FileName -match $filterType -or $item.VcUrl -match $filterType) {
                        $matchesFileType = $true
                        break
                    }
                }
                
                if (-not $matchesFileType) {
                    Write-Log -Message "  Skipping $($item.FileName) - doesn't match FileType filter" -Level "DEBUG" -Color DarkGray
                    continue
                }
                
                # Apply DaysBack filtering
                if ($DaysBack -and $DaysBack -gt 0) {
                    if ($item.FileName -match '^(\d{4})(\d{2})(\d{2})_(\d{4})_') {
                        try {
                            $year = [int]$matches[1]
                            $month = [int]$matches[2]
                            $day = [int]$matches[3]
                            $hour = [int]$matches[4].Substring(0,2)
                            $minute = [int]$matches[4].Substring(2,2)
                            
                            $fileDate = Get-Date -Year $year -Month $month -Day $day -Hour $hour -Minute $minute
                            $cutoffDate = (Get-Date).AddDays(-$DaysBack)
                            
                            if ($fileDate -lt $cutoffDate) {
                                $skipped++
                                Write-Log -Message "  SKIPPED: $($item.FileName) - older than $DaysBack days" -Level "WARN" -Color Yellow
                                continue
                            }
                        } catch {
                            Write-Log -Message "  Warning: Could not parse date from $($item.FileName)" -Level "WARN" -Color Yellow
                        }
                    }
                }
                
                # Determine local path
                $relativePath = if ($item.RelativePath) { $item.RelativePath.Trim('/') } else { "Counts/Count7511/Aggregates" }
                $localFilePath = Join-Path $localStagingDir $relativePath
                $localFilePath = Join-Path $localFilePath $item.FileName
                
                # Ensure directory exists
                $localDir = Split-Path $localFilePath -Parent
                if (-not (Test-Path $localDir)) {
                    New-Item -ItemType Directory -Path $localDir -Force | Out-Null
                }
                
                $allDownloads += [PSCustomObject]@{
                    FileName = $item.FileName
                    VcUrl = $item.VcUrl
                    LocalPath = $localFilePath
                    RelativePath = $item.RelativePath
                    CreationTime = $item.CreationTime
                    Status = $null
                    Size = $null
                    Time = $null
                    Details = $null
                }
            }
        }
        
        # Check if we have files to download
        if ($allDownloads.Count -eq 0) {
            $modeText = if ($RetryMode) { "retry" } else { "download" }
            Write-Log -Message "No files found for $modeText after filtering" -Level "WARN" -Color Yellow
            return @{ Downloaded = 0; Failed = 0; Skipped = $skipped; Error = $null }
        }
        
        $modeText = if ($RetryMode) { "retry download" } else { "download" }
        Write-Log -Message "Total files to $modeText`: $($allDownloads.Count)" -Level "INFO" -Color Green
        
        # ✅ PARALLEL DOWNLOAD EXECUTION
        Write-Log -Message "Starting parallel download with $MaxThreads threads..." -Level "INFO" -Color Green
        
        # Create thread-safe synchronization objects
        $syncHash = [hashtable]::Synchronized(@{})
        $lockObj = New-Object System.Object
        
        # Initialize runspace pool
        $runspacePool = [runspacefactory]::CreateRunspacePool(1, $MaxThreads)
        $runspacePool.Open()
        
        # Download script block
        $downloadScriptBlock = {
            param($download, $syncHash, $lockObj, $user, $useMSAL, $tokenFile, $isRetryMode)
            
            try {
                $downloadStartTime = Get-Date
                
                # Determine file type flag based on extension
                $fileTypeFlag = switch ([System.IO.Path]::GetExtension($download.FileName).ToLower()) {
                    ".tsv" { "-text" }
                    ".csv" { "-text" }
                    ".txt" { "-text" }
                    ".ss" { "-binary" }
                    default { "-text" }
                }
                
                # Build command with appropriate authentication
                if ($useMSAL -and (Test-Path $tokenFile)) {
                    $command = "scope.exe copy `"$($download.VcUrl)`" `"$($download.LocalPath)`" -on UseAadAuthentication -SecureInfoFile `"$tokenFile`" $fileTypeFlag 2>&1"
                } else {
                    $command = "scope.exe copy `"$($download.VcUrl)`" `"$($download.LocalPath)`" -on UseCachedCredentials -u $user $fileTypeFlag 2>&1"
                }
                
                $output = Invoke-Expression $command
                $downloadEndTime = Get-Date
                $duration = ($downloadEndTime - $downloadStartTime).TotalSeconds
                
                # Update download object with results
                $download.Time = "$([math]::Round($duration, 1))s"
                
                if ($LASTEXITCODE -eq 0) {
                    # Get file size
                    try {
                        if (Test-Path $download.LocalPath) {
                            $fileInfo = Get-Item $download.LocalPath -ErrorAction SilentlyContinue
                            if ($fileInfo -and $fileInfo.Length -gt 0) {
                                $sizeMB = [math]::Round($fileInfo.Length / 1MB, 2)
                                $download.Size = "$sizeMB MB"
                            } else {
                                $download.Size = "0.00 MB"
                            }
                        } else {
                            $download.Size = "File not found"
                        }
                    } catch {
                        $download.Size = "Size error"
                    }
                    
                    $download.Status = "Success"
                    $retryText = if ($isRetryMode) { " (retry successful)" } else { "" }
                    $download.Details = "Downloaded successfully$retryText"
                } else {
                    $download.Status = "Failed"
                    $download.Size = "0 MB"
                    
                    # ✅ CAPTURE COMPLETE ERROR MESSAGE - NO TRUNCATION
                    if ($output) {
                        if ($output -is [array]) {
                            # Join all output lines with proper separation
                            $fullError = ($output | Where-Object { $_ -and $_.ToString().Trim() } | ForEach-Object { $_.ToString().Trim() }) -join " | "
                        } else {
                            $fullError = $output.ToString().Trim()
                        }
                        
                        # If still too generic, add more context
                        if ($fullError -eq "1" -or $fullError.Length -lt 10) {
                            $fullError = "Scope copy command failed with exit code $LASTEXITCODE. Command: $command"
                        }
                        
                        $download.Details = $fullError
                    } else {
                        $download.Details = "Download failed with exit code $LASTEXITCODE. No output captured. Command: $command"
                    }
                }
                
                # Thread-safe result storage
                [System.Threading.Monitor]::Enter($lockObj)
                try {
                    if (-not $syncHash.ContainsKey('Results')) {
                        $syncHash.Results = [System.Collections.Generic.List[PSObject]]::new()
                    }
                    $syncHash.Results.Add($download)
                    
                    if ($download.Status -eq "Success") {
                        if (-not $syncHash.ContainsKey('Downloaded')) { $syncHash.Downloaded = 0 }
                        $syncHash.Downloaded++
                    } else {
                        if (-not $syncHash.ContainsKey('Failed')) { $syncHash.Failed = 0 }
                        $syncHash.Failed++
                    }
                } finally {
                    [System.Threading.Monitor]::Exit($lockObj)
                }
                
                return $download
                
            } catch {
                $download.Status = "Failed"
                $download.Size = "0 MB"
                $download.Time = "0s"
                $download.Details = "Exception during download: $($_.Exception.Message). Stack trace: $($_.ScriptStackTrace)"
                
                # Thread-safe error storage
                [System.Threading.Monitor]::Enter($lockObj)
                try {
                    if (-not $syncHash.ContainsKey('Results')) {
                        $syncHash.Results = [System.Collections.Generic.List[PSObject]]::new()
                    }
                    $syncHash.Results.Add($download)
                    
                    if (-not $syncHash.ContainsKey('Failed')) { $syncHash.Failed = 0 }
                    $syncHash.Failed++
                } finally {
                    [System.Threading.Monitor]::Exit($lockObj)
                }
                
                return $download
            }
        }
        
        # Start download jobs
        $downloadJobs = @()
        foreach ($download in $allDownloads) {
            $powerShell = [powershell]::Create()
            $powerShell.RunspacePool = $runspacePool
            
            [void]$powerShell.AddScript($downloadScriptBlock)
            [void]$powerShell.AddArgument($download)
            [void]$powerShell.AddArgument($syncHash)
            [void]$powerShell.AddArgument($lockObj)
            [void]$powerShell.AddArgument($user)
            [void]$powerShell.AddArgument($UseMSAL)
            [void]$powerShell.AddArgument("")  # tokenFile
            [void]$powerShell.AddArgument($RetryMode)
            
            $downloadJobs += @{
                PowerShell = $powerShell
                Handle = $powerShell.BeginInvoke()
                IsCompleted = $false
            }
        }
        
        Write-Log -Message "Monitoring $($downloadJobs.Count) parallel download jobs..." -Level "INFO" -Color Cyan
        
        # Monitor progress
        $completedJobs = 0
        $lastProgressUpdate = Get-Date
        
        while ($completedJobs -lt $downloadJobs.Count) {
            Start-Sleep -Milliseconds 500
            
            $newlyCompleted = 0
            foreach ($job in $downloadJobs) {
                if ($job.Handle.IsCompleted -and -not $job.IsCompleted) {
                    try {
                        $result = $job.PowerShell.EndInvoke($job.Handle)
                        $job.IsCompleted = $true
                        $completedJobs++
                        $newlyCompleted++
                        
                        # ✅ SHOW COMPLETE ERROR MESSAGES IN CONSOLE
                        if ($result -and $result.Status) {
                            if ($result.Status -eq "Success") {
                                Write-Log -Message "  SUCCESS: $($result.FileName) ($($result.Size) in $($result.Time))" -Level "SUCCESS" -Color Green
                            } else {
                                Write-Log -Message "  FAILED: $($result.FileName)" -Level "ERROR" -Color Red
                                if ($result.Details) {
                                    Write-Log -Message "    Full Error: $($result.Details)" -Level "ERROR" -Color Red
                                }
                            }
                        }
                    } catch {
                        Write-Log -Message "  ERROR processing job result: $($_.Exception.Message)" -Level "ERROR" -Color Red
                        $job.IsCompleted = $true
                        $completedJobs++
                    } finally {
                        $job.PowerShell.Dispose()
                    }
                }
            }
            
            # Show progress every 10 seconds or when jobs complete
            $now = Get-Date
            if ($newlyCompleted -gt 0 -or ($now - $lastProgressUpdate).TotalSeconds -ge 10) {
                $progressPercent = [math]::Round(($completedJobs / $downloadJobs.Count) * 100, 1)
                Write-Log -Message "Download Progress: $completedJobs/$($downloadJobs.Count) completed ($progressPercent%)" -Level "INFO" -Color Cyan
                $lastProgressUpdate = $now
            }
            
            if ($global:CleanupInProgress) { break }
        }
        
        # Cleanup
        Write-Log -Message "Cleaning up download resources..." -Level "INFO" -Color Yellow
        $runspacePool.Close()
        $runspacePool.Dispose()
        
        # Collect results
        $downloadResults = if ($syncHash.Results) { @($syncHash.Results.ToArray()) } else { @() }
        $downloaded = if ($syncHash.Downloaded) { $syncHash.Downloaded } else { 0 }
        $failed = if ($syncHash.Failed) { $syncHash.Failed } else { 0 }
        
        Write-Log -Message "Download Results: $downloaded succeeded, $failed failed, $skipped skipped" -Level "SUCCESS" -Color Green
        
        # ✅ CONVERT RESULTS TO EXISTING FORMAT FOR COMPATIBILITY
        $global:DownloadResults.Clear()
        foreach ($download in $downloadResults) {
            $global:DownloadResults.Add([PSCustomObject]@{
                FileName = $download.FileName
                Status = if ($download.Status) { $download.Status } else { "Unknown" }
                Size = if ($download.Size) { $download.Size } else { "0 MB" }
                Time = if ($download.Time) { $download.Time } else { "0s" }
                CreationDate = $download.CreationTime
                Path = $download.RelativePath
                Details = if ($download.Details) { $download.Details } else { "No details available" }
                VcUrl = $download.VcUrl
            })
        }
        
        # Save error files if there were failures
        if ($failed -gt 0) {
            Save-ErrorFiles -OperationType "Download" -Results $global:DownloadResults
        }
        
        return @{ Downloaded = $downloaded; Failed = $failed; Skipped = $skipped; Error = $null }
        
    } catch {
        Write-Log -Message "Error in Phase2-DownloadToLocal: $($_.Exception.Message)" -Level "ERROR" -Color Red
        return @{ Downloaded = 0; Failed = 1; Skipped = 0; Error = $_.Exception.Message }
    } 
    finally {
    $phaseEnd = Get-Date
    $phaseDuration = $phaseEnd - $phaseStart
    Write-Log -Message "==== END PHASE: Phase3-UploadToDestination | Duration: $($phaseDuration.ToString('hh\:mm\:ss')) ====" -Level "PHASE" -Color Magenta
    
    # ✅ FIXED: Add to phase summaries with proper error handling
    try {
        # Ensure PhaseSummaries is initialized as a list
        if (-not $global:PhaseSummaries) {
            $global:PhaseSummaries = [System.Collections.Generic.List[PSObject]]::new()
        }
        
        # Create phase summary object
        $phaseSummary = [PSCustomObject]@{
            Phase = "Phase3-DownloadToLocal"  # Change this to appropriate phase name
            Duration = $phaseDuration
            Data = @{ Uploaded = $uploaded; Failed = $failed; Skipped = $skipped }
        }
        
        # Add to global collection
        $global:PhaseSummaries.Add($phaseSummary)
        
    } catch {
        Write-Log -Message "Warning: Could not add phase summary: $($_.Exception.Message)" -Level "WARN" -Color Yellow
    }
}
}

# ================================================================================================
# COMPLETE Phase3-UploadToDestination FUNCTION WITH UPLOAD FUNCTIONALITY
# Current Date and Time (UTC): 2025-08-12 05:55:47
# Current User: varadharajaan
# ================================================================================================

function Phase3-UploadToDestination {
    param([hashtable]$PhaseData = @{})
    
    $phaseStart = Get-Date
    Write-Log -Message "==== START PHASE: Phase3-UploadToDestination ====" -Level "PHASE" -Color Magenta
    
    try {
        # Set destination and user
        $destination_https = "vc://cosmos08/bingads.algo.adquality/local/users/varadharajaan/ThemisINTL/"
        $user = "varadharajaan@microsoft.com"
        
        Write-Log -Message "Destination set to: $destination_https" -Level "INFO" -Color Cyan
        Write-Log -Message "Phase 3: Parallel Upload to Cosmos destination" -Level "INFO" -Color Green
        Write-Log -Message "Max Threads: $MaxThreads" -Level "INFO" -Color Cyan
        Write-Log -Message "Source: $localStagingDir" -Level "INFO" -Color Cyan
        Write-Log -Message "Destination: $destination_https" -Level "INFO" -Color Cyan
        Write-Log -Message "User: $user" -Level "INFO" -Color Cyan
        
        # Initialize counters
        $uploaded = 0
        $failed = 0
        $skipped = 0
        
        # Directory configurations
        $directoryConfigs = @(
            @{ Type = "Count7511"; Path = "Counts/Count7511/Aggregates/" },
            @{ Type = "Count7513"; Path = "Counts/Count7513/Aggregates/" },
            @{ Type = "Count7515"; Path = "Counts/Count7515/Aggregates/" },
            @{ Type = "PipelineRunState"; Path = "PipelineRunState/" },
            @{ Type = "V1Monitor"; Path = "V1/Monitor/" },
            @{ Type = "V2Monitor"; Path = "V2/Monitor/" },
            @{ Type = "V1Daily"; Path = "V1/Daily/" },
            @{ Type = "V2Daily"; Path = "V2/Daily/" }
        )
        
        $allUploads = @()
        
        # ✅ RETRY MODE LOGIC FOR UPLOADS
        if ($RetryMode -and -not [string]::IsNullOrEmpty($ErrorFile)) {
            Write-Log -Message "RETRY MODE: Loading files from error file..." -Level "INFO" -Color Magenta
            
            try {
                if (-not (Test-Path $ErrorFile)) {
                    Write-Log -Message "Error file not found: $ErrorFile" -Level "ERROR" -Color Red
                    return @{ Uploaded = 0; Failed = 1; Skipped = 0; Error = "Error file not found" }
                }
                
                $retryFiles = Import-Csv -Path $ErrorFile
                Write-Log -Message "Loaded $($retryFiles.Count) entries from error file" -Level "INFO" -Color Green
                
                foreach ($retryFile in $retryFiles) {
                    # For upload retries, files should be in local staging directory
                    $localFilePath = ""
                    
                    # Try to find the file in local staging directory
                    if ($retryFile.LocalPath -and (Test-Path $retryFile.LocalPath)) {
                        $localFilePath = $retryFile.LocalPath
                    } elseif ($retryFile.FileName) {
                        # Search for file in staging directory structure
                        $searchPaths = @(
                            (Join-Path $localStagingDir "Counts\Count7511\Aggregates\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "Counts\Count7513\Aggregates\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "Counts\Count7515\Aggregates\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "V1\Daily\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "V2\Daily\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "V1\Monitor\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "V2\Monitor\$($retryFile.FileName)"),
                            (Join-Path $localStagingDir "PipelineRunState\$($retryFile.FileName)")
                        )
                        
                        foreach ($searchPath in $searchPaths) {
                            if (Test-Path $searchPath) {
                                $localFilePath = $searchPath
                                break
                            }
                        }
                    }
                    
                    if ($localFilePath -and (Test-Path $localFilePath)) {
                        # Determine destination URL
                        $destinationUrl = ""
                        if ($retryFile.VcUrl -and $retryFile.VcUrl -ne "LOCAL_FILE" -and $retryFile.VcUrl -ne "N/A") {
                            $destinationUrl = $retryFile.VcUrl
                        } else {
                            # Reconstruct destination URL
                            $relativePath = if ($retryFile.RelativePath) { $retryFile.RelativePath } else { "Counts/Count7511/Aggregates/" }
                            if (-not $relativePath.EndsWith('/')) { $relativePath += '/' }
                            $destinationUrl = $destination_https + $relativePath + $retryFile.FileName
                            $destinationUrl = $destinationUrl -replace "(?<!:)//+", "/"
                        }
                        
                        $allUploads += [PSCustomObject]@{
                            LocalPath = $localFilePath
                            FileName = $retryFile.FileName
                            DestinationUrl = $destinationUrl
                            RelativePath = if ($retryFile.RelativePath) { $retryFile.RelativePath } else { "Counts/Count7511/Aggregates/" }
                            Status = $null
                            Size = $null
                            Time = $null
                            Details = $null
                            OriginalError = if ($retryFile.OriginalError) { $retryFile.OriginalError } else { $retryFile.Details }
                        }
                        
                        Write-Log -Message "  Queued for retry: $($retryFile.FileName)" -Level "DEBUG" -Color DarkGray
                    } else {
                        Write-Log -Message "  File not found locally: $($retryFile.FileName)" -Level "WARN" -Color Yellow
                    }
                }
                
                Write-Log -Message "RETRY MODE: Loaded $($allUploads.Count) files for retry upload" -Level "SUCCESS" -Color Green
                
            } catch {
                Write-Log -Message "Error loading retry file: $($_.Exception.Message)" -Level "ERROR" -Color Red
                return @{ Uploaded = 0; Failed = 1; Skipped = 0; Error = "Error loading retry file" }
            }
            
        } else {
            # ✅ NORMAL MODE: Scan local staging directory for files to upload
            Write-Log -Message "NORMAL MODE: Scanning local staging directory..." -Level "INFO" -Color Green
            
            # Apply DaysBack filtering
            if ($DaysBack -and $DaysBack -gt 0) {
                Write-Log -Message "DaysBack filtering: ENABLED - only files from last $DaysBack days" -Level "INFO" -Color Yellow
            } else {
                Write-Log -Message "DaysBack filtering: DISABLED - uploading all files" -Level "INFO" -Color Green
            }
            
            # Parse FileType
            $fileTypeFilters = Parse-FileTypes -FileTypeString $FileType
            Write-Log -Message "FileType specified: $($fileTypeFilters -join ',')" -Level "INFO" -Color Cyan
            
            # Check which file types are available
            Write-Log -Message "Checking which file types are available..." -Level "INFO" -Color Cyan
            $availableTypes = @()
            foreach ($config in $directoryConfigs) {
                $availableTypes += $config.Type
            }
            
            # Validate FileType filters
            $validFilters = @()
            foreach ($filter in $fileTypeFilters) {
                $matchFound = $false
                foreach ($availableType in $availableTypes) {
                    if ($filter.ToLower() -eq $availableType.ToLower()) {
                        $validFilters += $filter
                        $matchFound = $true
                        break
                    }
                }
                if (-not $matchFound) {
                    Write-Log -Message "  ✗ No config found for: $filter" -Level "WARN" -Color Yellow
                    Write-Log -Message "    Available types: $($availableTypes -join ', ')" -Level "INFO" -Color Yellow
                }
            }
            
            if ($validFilters.Count -eq 0) {
                Write-Log -Message "No valid file types found. Available types: $($availableTypes -join ', ')" -Level "ERROR" -Color Red
                return @{ Uploaded = 0; Failed = 1; Skipped = 0; Error = "No valid file types" }
            }
            
            # ✅ Get existing files from destination for DaysBack filtering (only in normal mode)
            $existingFilesMap = @{}
            if ($DaysBack -and $DaysBack -gt 0) {
                Write-Log -Message "Checking existing files in destination for DaysBack filtering..." -Level "INFO" -Color Cyan
                
                foreach ($config in $directoryConfigs) {
                    $typeMatches = $validFilters | Where-Object { $_.ToLower() -eq $config.Type.ToLower() }
                    if (-not $typeMatches) { continue }
                    
                    $remotePath = $destination_https + $config.Path.TrimEnd('/')
                    $remotePath = $remotePath -replace "(?<!:)//+", "/"
                    
                    try {
                        Write-Log -Message "  Listing files in: $remotePath" -Level "DEBUG" -Color DarkGray
                        $listCommand = "scope.exe dir `"$remotePath`" -on UseCachedCredentials -u vdamotharan@microsoft.com 2>&1    "
                        $listOutput = Invoke-Expression $listCommand
                        
                        if ($LASTEXITCODE -eq 0 -and $listOutput) {
                            $lines = $listOutput -split "`n" | Where-Object { $_ -and $_ -notmatch "Directory of" -and $_ -notmatch "^\s*$" }
                            
                            foreach ($line in $lines) {
                                if ($line -match '(\d{8}_\d{4}_\w+.*\.(ss|tsv|csv))') {
                                    $fileName = $matches[1]
                                    
                                    if ($fileName -match '^(\d{4})(\d{2})(\d{2})_(\d{4})_') {
                                        try {
                                            $year = [int]$matches[1]
                                            $month = [int]$matches[2] 
                                            $day = [int]$matches[3]
                                            $hour = [int]$matches[4].Substring(0,2)
                                            $minute = [int]$matches[4].Substring(2,2)
                                            
                                            $fileDate = Get-Date -Year $year -Month $month -Day $day -Hour $hour -Minute $minute
                                            $existingFilesMap[$fileName] = $fileDate
                                            
                                            Write-Log -Message "    Found: $fileName (Date: $($fileDate.ToString('yyyy-MM-dd HH:mm')))" -Level "DEBUG" -Color DarkGray
                                        } catch {
                                            Write-Log -Message "    Warning: Could not parse date from $fileName" -Level "WARN" -Color Yellow
                                        }
                                    }
                                }
                            }
                        } else {
                            Write-Log -Message "    No files found or error listing: $remotePath" -Level "DEBUG" -Color DarkGray
                        }
                    } catch {
                        Write-Log -Message "    Error listing remote directory: $($_.Exception.Message)" -Level "WARN" -Color Yellow
                    }
                }
                
                Write-Log -Message "Found $($existingFilesMap.Count) existing files for comparison" -Level "INFO" -Color Green
            }
            
            # Scan local staging directory for files to upload
            foreach ($config in $directoryConfigs) {
                if ($global:CleanupInProgress) { break }
                
                if (-not $config -or -not $config.Type -or -not $config.Path) { continue }
                
                $typeMatches = $validFilters | Where-Object { $_.ToLower() -eq $config.Type.ToLower() }
                if (-not $typeMatches) { 
                    Write-Log -Message "  Skipping $($config.Type) - not in filter list" -Level "DEBUG" -Color DarkGray
                    continue 
                }
                
                $configPath = $config.Path.TrimEnd('/')
                $localSubDir = Join-Path $localStagingDir $configPath
                
                if (Test-Path $localSubDir) {
                    Write-Log -Message "Scanning for $($config.Type) files in: $localSubDir" -Level "INFO" -Color DarkCyan
                    
                    $localFiles = Get-ChildItem -Path $localSubDir -File | Where-Object {
                        $_.Name -notmatch "^\..*" -and $_.Length -gt 0
                    }
                    
                    Write-Log -Message "  Found $($localFiles.Count) total files in $($config.Type)" -Level "INFO" -Color DarkGreen
                    
                    # Apply DaysBack filtering and build upload list
                    $filteredFiles = @()
                    foreach ($file in $localFiles) {
                        if (-not $file -or -not $file.Name) { continue }
                        
                        $shouldUpload = $true
                        $skipReason = ""
                        
                        # Apply DaysBack filtering if specified
                        if ($DaysBack -and $DaysBack -gt 0) {
                            if ($file.Name -match '^(\d{4})(\d{2})(\d{2})_(\d{4})_') {
                                try {
                                    $year = [int]$matches[1]
                                    $month = [int]$matches[2]
                                    $day = [int]$matches[3]
                                    $hour = [int]$matches[4].Substring(0,2)
                                    $minute = [int]$matches[4].Substring(2,2)
                                    
                                    $localFileDate = Get-Date -Year $year -Month $month -Day $day -Hour $hour -Minute $minute
                                    $cutoffDate = (Get-Date).AddDays(-$DaysBack)
                                    
                                    if ($localFileDate -lt $cutoffDate) {
                                        $shouldUpload = $false
                                        $skipReason = "File older than $DaysBack days cutoff ($($localFileDate.ToString('yyyy-MM-dd')))"
                                    } else {
                                        if ($existingFilesMap.ContainsKey($file.Name)) {
                                            $existingFileDate = $existingFilesMap[$file.Name]
                                            if ($existingFileDate -ge $localFileDate) {
                                                $shouldUpload = $false
                                                $skipReason = "Newer/same version exists in destination ($($existingFileDate.ToString('yyyy-MM-dd')))"
                                            }
                                        }
                                    }
                                } catch {
                                    Write-Log -Message "    Warning: Could not parse date from local file $($file.Name)" -Level "WARN" -Color Yellow
                                }
                            }
                        }
                        
                        if ($shouldUpload) {
                            $filteredFiles += $file
                        } else {
                            $skipped++
                            Write-Log -Message "  SKIPPED: $($file.Name) - $skipReason" -Level "WARN" -Color Yellow
                        }
                    }
                    
                    Write-Log -Message "  After filtering: $($filteredFiles.Count) files to upload, $skipped skipped" -Level "INFO" -Color Green
                    
                    # Process filtered files for upload
                    foreach ($file in $filteredFiles) {
                        $relativePath = $config.Path
                        if (-not $relativePath.EndsWith('/')) { $relativePath += '/' }
                        
                        $destinationUrl = $destination_https + $relativePath + $file.Name
                        $destinationUrl = $destinationUrl -replace "(?<!:)//+", "/"
                        
                        $allUploads += [PSCustomObject]@{
                            LocalPath = $file.FullName
                            FileName = $file.Name
                            DestinationUrl = $destinationUrl
                            RelativePath = $relativePath
                            Status = $null
                            Size = $null
                            Time = $null
                            Details = $null
                        }
                        
                        Write-Log -Message "  Queued: $($file.Name)" -Level "DEBUG" -Color DarkGray
                    }
                } else {
                    Write-Log -Message "  Directory not found: $localSubDir" -Level "WARN" -Color Yellow
                }
            }
        }
        
        # Check if we have files to upload
        if ($allUploads.Count -eq 0) {
            $modeText = if ($RetryMode) { "retry" } else { "upload" }
            Write-Log -Message "No files found for $modeText after filtering" -Level "WARN" -Color Yellow
            return @{ Uploaded = 0; Failed = 0; Skipped = $skipped; Error = $null }
        }
        
        $modeText = if ($RetryMode) { "retry upload" } else { "upload" }
        Write-Log -Message "Total files to $modeText`: $($allUploads.Count)" -Level "INFO" -Color Green
        
        # ✅ PARALLEL UPLOAD EXECUTION
        Write-Log -Message "Starting parallel upload with $MaxThreads threads..." -Level "INFO" -Color Green
        
        # Create thread-safe synchronization objects
        $syncHash = [hashtable]::Synchronized(@{})
        $lockObj = New-Object System.Object
        
        # Initialize runspace pool
        $runspacePool = [runspacefactory]::CreateRunspacePool(1, $MaxThreads)
        $runspacePool.Open()
        
        # Upload script block
        $uploadScriptBlock = {
            param($upload, $syncHash, $lockObj, $expiry_days)
            
            try {
                $uploadStartTime = Get-Date
                
                # Determine file type flag based on extension
                $fileFlag = if ($upload.FileName.EndsWith('.ss')) { '-binary' } else { '-text' }
                
                # Create destination directory first
                $destinationDir = $upload.DestinationUrl.Substring(0, $upload.DestinationUrl.LastIndexOf('/'))
                
                $createDirCommand = "scope.exe mkdir `"$destinationDir`" -on UseCachedCredentials -u varadharajaan@microsoft.com 2>&1"
                $createDirOutput = Invoke-Expression $createDirCommand
                # Don't check exit code for mkdir - it fails if directory exists
                
                # ✅ CORRECT: Use proper scope command with correct parameters
                if ($expiry_days -and $expiry_days -gt 0) {
                    $command = "scope.exe copy `"$($upload.LocalPath)`" `"$($upload.DestinationUrl)`" -on UseCachedCredentials -u varadharajaan@microsoft.com $fileFlag -expirationtime $expiry_days"
                } else {
                    $command = "scope.exe copy `"$($upload.LocalPath)`" `"$($upload.DestinationUrl)`" -on UseCachedCredentials -u varadharajaan@microsoft.com $fileFlag"
                }
                
                $output = Invoke-Expression $command
                $uploadEndTime = Get-Date
                $duration = ($uploadEndTime - $uploadStartTime).TotalSeconds
                
                # Get file size
                $sizeBytes = (Get-Item $upload.LocalPath).Length
                $sizeMB = [math]::Round($sizeBytes / 1MB, 2)
                
                # Update upload object with results
                $upload.Size = "$sizeMB MB"
                $upload.Time = "$([math]::Round($duration, 1))s"
                
                if ($LASTEXITCODE -eq 0) {
                    # Success
                    $upload.Status = "Success"
                    $upload.Details = "Upload completed successfully"
                } else {
                    $upload.Status = "Failed"
                    
                    # ✅ CAPTURE COMPLETE ERROR MESSAGE - NO TRUNCATION
                    if ($output) {
                        if ($output -is [array]) {
                            # Join all output lines with proper separation
                            $fullError = ($output | Where-Object { $_ -and $_.ToString().Trim() } | ForEach-Object { $_.ToString().Trim() }) -join " | "
                        } else {
                            $fullError = $output.ToString().Trim()
                        }
                        
                        # If still too generic, add more context
                        if ($fullError -eq "1" -or $fullError.Length -lt 10) {
                            $fullError = "Scope copy command failed with exit code $LASTEXITCODE. Command: $command"
                        }
                        
                        $upload.Details = $fullError
                    } else {
                        $upload.Details = "Upload failed with exit code $LASTEXITCODE. No output captured. Command: $command"
                    }
                }
                
                # Thread-safe result storage
                [System.Threading.Monitor]::Enter($lockObj)
                try {
                    if (-not $syncHash.ContainsKey('Results')) {
                        $syncHash.Results = [System.Collections.Generic.List[PSObject]]::new()
                    }
                    $syncHash.Results.Add($upload)
                    
                    if ($upload.Status -eq "Success") {
                        if (-not $syncHash.ContainsKey('Uploaded')) { $syncHash.Uploaded = 0 }
                        $syncHash.Uploaded++
                    } else {
                        if (-not $syncHash.ContainsKey('Failed')) { $syncHash.Failed = 0 }
                        $syncHash.Failed++
                    }
                } finally {
                    [System.Threading.Monitor]::Exit($lockObj)
                }
                
                return $upload
                
            } catch {
                $upload.Status = "Failed"
                $upload.Size = "0 MB"
                $upload.Time = "0s"
                $upload.Details = "Exception during upload: $($_.Exception.Message). Stack trace: $($_.ScriptStackTrace)"
                
                # Thread-safe error storage
                [System.Threading.Monitor]::Enter($lockObj)
                try {
                    if (-not $syncHash.ContainsKey('Results')) {
                        $syncHash.Results = [System.Collections.Generic.List[PSObject]]::new()
                    }
                    $syncHash.Results.Add($upload)
                    
                    if (-not $syncHash.ContainsKey('Failed')) { $syncHash.Failed = 0 }
                    $syncHash.Failed++
                } finally {
                    [System.Threading.Monitor]::Exit($lockObj)
                }
                
                return $upload
            }
        }
        
        # Start upload jobs
        $uploadJobs = @()
        foreach ($upload in $allUploads) {
            $powerShell = [powershell]::Create()
            $powerShell.RunspacePool = $runspacePool
            
            [void]$powerShell.AddScript($uploadScriptBlock)
            [void]$powerShell.AddArgument($upload)
            [void]$powerShell.AddArgument($syncHash)
            [void]$powerShell.AddArgument($lockObj)
            [void]$powerShell.AddArgument($expiry_days)
            
            $uploadJobs += @{
                PowerShell = $powerShell
                Handle = $powerShell.BeginInvoke()
                IsCompleted = $false
            }
        }
        
        Write-Log -Message "Monitoring $($uploadJobs.Count) parallel upload jobs..." -Level "INFO" -Color Cyan
        
        # Monitor progress
        $completedJobs = 0
        $lastProgressUpdate = Get-Date
        
        while ($completedJobs -lt $uploadJobs.Count) {
            Start-Sleep -Milliseconds 500
            
            $newlyCompleted = 0
            foreach ($job in $uploadJobs) {
                if ($job.Handle.IsCompleted -and -not $job.IsCompleted) {
                    try {
                        $result = $job.PowerShell.EndInvoke($job.Handle)
                        $job.IsCompleted = $true
                        $completedJobs++
                        $newlyCompleted++
                        
                        # ✅ SHOW COMPLETE ERROR MESSAGES IN CONSOLE
                        if ($result -and $result.Status) {
                            if ($result.Status -eq "Success") {
                                Write-Log -Message "  SUCCESS: $($result.FileName) ($($result.Size) in $($result.Time))" -Level "SUCCESS" -Color Green
                            } else {
                                Write-Log -Message "  FAILED: $($result.FileName)" -Level "ERROR" -Color Red
                                if ($result.Details) {
                                    Write-Log -Message "    Full Error: $($result.Details)" -Level "ERROR" -Color Red
                                }
                            }
                        }
                    } catch {
                        Write-Log -Message "  ERROR processing job result: $($_.Exception.Message)" -Level "ERROR" -Color Red
                        $job.IsCompleted = $true
                        $completedJobs++
                    } finally {
                        $job.PowerShell.Dispose()
                    }
                }
            }
            
            # Show progress every 10 seconds or when jobs complete
            $now = Get-Date
            if ($newlyCompleted -gt 0 -or ($now - $lastProgressUpdate).TotalSeconds -ge 10) {
                $progressPercent = [math]::Round(($completedJobs / $uploadJobs.Count) * 100, 1)
                Write-Log -Message "Upload Progress: $completedJobs/$($uploadJobs.Count) completed ($progressPercent%)" -Level "INFO" -Color Cyan
                $lastProgressUpdate = $now
            }
            
            if ($global:CleanupInProgress) { break }
        }
        
        # Cleanup
        Write-Log -Message "Cleaning up upload resources..." -Level "INFO" -Color Yellow
        $runspacePool.Close()
        $runspacePool.Dispose()
        
        # Collect results
        $uploadResults = if ($syncHash.Results) { @($syncHash.Results.ToArray()) } else { @() }
        $uploaded = if ($syncHash.Uploaded) { $syncHash.Uploaded } else { 0 }
        $failed = if ($syncHash.Failed) { $syncHash.Failed } else { 0 }
        
        Write-Log -Message "Upload Results: $uploaded succeeded, $failed failed, $skipped skipped" -Level "SUCCESS" -Color Green
        
        # ✅ CONVERT RESULTS TO EXISTING FORMAT FOR COMPATIBILITY
        $global:UploadResults.Clear()
        foreach ($upload in $uploadResults) {
            $global:UploadResults.Add([PSCustomObject]@{
                FileName = $upload.FileName
                Status = if ($upload.Status) { $upload.Status } else { "Unknown" }
                Size = if ($upload.Size) { $upload.Size } else { "0 MB" }
                Time = if ($upload.Time) { $upload.Time } else { "0s" }
                LocalPath = $upload.LocalPath
                DestinationUrl = $upload.DestinationUrl
                RelativePath = $upload.RelativePath
                Details = if ($upload.Details) { $upload.Details } else { "No details available" }
                VcUrl = $upload.DestinationUrl
            })
        }
        
        # Save error files if there were failures
        if ($failed -gt 0) {
            Save-ErrorFiles -OperationType "Upload" -Results $global:UploadResults
        }
        
        return @{ Uploaded = $uploaded; Failed = $failed; Skipped = $skipped; Error = $null }
        
    } catch {
        Write-Log -Message "Error in Phase3-UploadToDestination: $($_.Exception.Message)" -Level "ERROR" -Color Red
        return @{ Uploaded = 0; Failed = 1; Skipped = 0; Error = $_.Exception.Message }
    } finally {
    $phaseEnd = Get-Date
    $phaseDuration = $phaseEnd - $phaseStart
    Write-Log -Message "==== END PHASE: Phase3-UploadToDestination | Duration: $($phaseDuration.ToString('hh\:mm\:ss')) ====" -Level "PHASE" -Color Magenta
    
    # ✅ FIXED: Add to phase summaries with proper error handling
    try {
        # Ensure PhaseSummaries is initialized as a list
        if (-not $global:PhaseSummaries) {
            $global:PhaseSummaries = [System.Collections.Generic.List[PSObject]]::new()
        }
        
        # Create phase summary object
        $phaseSummary = [PSCustomObject]@{
            Phase = "Phase3-UploadToDestination"  # Change this to appropriate phase name
            Duration = $phaseDuration
            Data = @{ Uploaded = $uploaded; Failed = $failed; Skipped = $skipped }
        }
        
        # Add to global collection
        $global:PhaseSummaries.Add($phaseSummary)
        
    } catch {
        Write-Log -Message "Warning: Could not add phase summary: $($_.Exception.Message)" -Level "WARN" -Color Yellow
    }
}
}

# ================================================================================================
# MAIN EXECUTION
# ================================================================================================
Write-Log -Message "THEMIS FILE MANAGEMENT SCRIPT - WITHOUT METADATA EXTRACTION" -Level "START" -Color Cyan
Write-Log -Message "Current Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') UTC" -Level "INFO" -Color Cyan
Write-Log -Message "Current User: $env:USERNAME" -Level "INFO" -Color Cyan

try {
    # Parse phases dynamically
    $requestedPhases = $Phase -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
    
    if ($Phase -eq "all") {
        $requestedPhases = @("1", "2", "3")
    }
    
    # Validate phases
    $validPhases = @("1", "2", "3")
    $invalidPhases = $requestedPhases | Where-Object { $_ -notin $validPhases }
    
    if ($invalidPhases.Count -gt 0) {
        Write-Log -Message "Invalid phases: $($invalidPhases -join ', '). Valid phases are: $($validPhases -join ', '), or 'all'" -Level "ERROR" -Color Red
        exit 1
    } else {
        Write-Log -Message "Executing phases: $($requestedPhases -join ', ')" -Level "INFO" -Color Cyan
        
        foreach ($phaseNum in $requestedPhases) {
            if ($global:CleanupInProgress) { break }
            
            try {
                switch ($phaseNum) {
                    "1" { 
                        Write-Log -Message "Starting Phase 1: List All Files" -Level "INFO" -Color Green
                        $result = Phase1-ListAllFiles
                        $global:PhaseResults["Phase1"] = $result
                    }
                    "2" { 
                        Write-Log -Message "Starting Phase 2: Download To Local" -Level "INFO" -Color Green
                        $result = Phase2-DownloadToLocal
                        $global:PhaseResults["Phase2"] = $result
                        
                        # ✅ Show download failure report if there were failures
                        if ($global:DownloadResults) {
                            Show-FinalFailureReport -OperationType "DOWNLOAD"
                        }
                    }
                    "3" { 
                        Write-Log -Message "Starting Phase 3: Upload To Destination" -Level "INFO" -Color Green
                        $result = Phase3-UploadToDestination
                        $global:PhaseResults["Phase3"] = $result
                        
                        # ✅ Show upload failure report if there were failures
                        if ($global:UploadResults) {
                            Show-FinalFailureReport -OperationType "UPLOAD"
                        }
                    }
                }
            } catch {
                Write-Log -Message "Error in Phase $phaseNum`: $($_.Exception.Message)" -Level "ERROR" -Color Red

                # Continue with other phases instead of stopping completely
            }
        }
    }
} catch {
    Write-Log -Message "Fatal error: $_" -Level "ERROR" -Color Red
    # ✅ FIX: Check if cleanup function exists before calling
    if (Get-Command "Cleanup-Resources" -ErrorAction SilentlyContinue) {
        Cleanup-Resources
    }
} finally {
    # ✅ FIX: Check if cleanup variables exist and cleanup function exists
    if ((Get-Command "Cleanup-Resources" -ErrorAction SilentlyContinue) -and 
        (($global:RunspacePools -and $global:RunspacePools.Count -gt 0) -or 
         ($global:ActiveJobs -and $global:ActiveJobs.Count -gt 0) -or 
         $global:TokenMonitorJob)) {
        Write-Log -Message "Performing final cleanup..." -Level "INFO" -Color Yellow
        Cleanup-Resources
    }
}

if (-not $global:CleanupInProgress) {
    Write-Host ""
    Write-Log -Message "EXECUTION SUMMARY" -Level "SUMMARY" -Color Cyan
    
    # ✅ FIX: Check if PhaseSummaries exists before using
    if ($global:PhaseSummaries -and $global:PhaseSummaries.Count -gt 0) {
        foreach ($ps in $global:PhaseSummaries) {
            $dataStr = if ($ps.Data) { ($ps.Data.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', ' } else { "N/A" }
            Write-Host ("{0,-30} Duration={1,-12} Data={2}" -f $ps.Phase, $ps.Duration.ToString("hh\:mm\:ss"), $dataStr)
        }
    } else {
        Write-Log -Message "No phase summaries available" -Level "INFO" -Color Yellow
    }
    
    Write-Log -Message "SCRIPT COMPLETED SUCCESSFULLY" -Level "END" -Color Green
    
    # ✅ FIX: Use correct variable names
    if ($reportsDir) {
        Write-Log -Message "Reports available in: $reportsDir" -Level "INFO" -Color Cyan
    }
    
    if ($UseMSAL) {
        Write-Log -Message "MSAL token file cleaned up" -Level "INFO" -Color Cyan
    }
    
    if ($errorDir) {
        Write-Log -Message "Error files (if any) available in: $errorDir" -Level "INFO" -Color Cyan
    }
    
    # Show total script execution time
    if ($global:ScriptStart) {
        $totalDuration = New-TimeSpan -Start $global:ScriptStart -End (Get-Date)
        Write-Log -Message "Total Script Duration: $($totalDuration.ToString('hh\:mm\:ss'))" -Level "INFO" -Color Green
    }
    
    # ✅ IMPROVED: Show final statistics based on actual results
    Write-Host ""
    Write-Log -Message "FINAL STATISTICS" -Level "SUMMARY" -Color Cyan
    
    $totalProcessed = 0
    $totalSucceeded = 0
    $totalFailed = 0
    $totalSkipped = 0
    
    # Count download results
    if ($global:DownloadResults -and $global:DownloadResults.Count -gt 0) {
        $downloadStats = @($global:DownloadResults.ToArray())
        $downloadSuccess = ($downloadStats | Where-Object { $_.Status -eq "Success" }).Count
        $downloadFailed = ($downloadStats | Where-Object { $_.Status -eq "Failed" }).Count
        $downloadSkipped = ($downloadStats | Where-Object { $_.Status -eq "Skipped" }).Count
        
        $totalProcessed += $downloadStats.Count
        $totalSucceeded += $downloadSuccess
        $totalFailed += $downloadFailed
        $totalSkipped += $downloadSkipped
        
        Write-Host "📥 DOWNLOADS: $downloadSuccess succeeded, $downloadFailed failed, $downloadSkipped skipped" -ForegroundColor Cyan
    }
    
    # Count upload results
    if ($global:UploadResults -and $global:UploadResults.Count -gt 0) {
        $uploadStats = @($global:UploadResults.ToArray())
        $uploadSuccess = ($uploadStats | Where-Object { $_.Status -eq "Success" }).Count
        $uploadFailed = ($uploadStats | Where-Object { $_.Status -eq "Failed" }).Count
        $uploadSkipped = ($uploadStats | Where-Object { $_.Status -eq "Skipped" }).Count
        
        $totalProcessed += $uploadStats.Count
        $totalSucceeded += $uploadSuccess
        $totalFailed += $uploadFailed
        $totalSkipped += $uploadSkipped
        
        Write-Host "📤 UPLOADS: $uploadSuccess succeeded, $uploadFailed failed, $uploadSkipped skipped" -ForegroundColor Cyan
    }
    
    # Show overall totals
    if ($totalProcessed -gt 0) {
        Write-Host ""
        Write-Host "📊 OVERALL TOTALS:" -ForegroundColor White
        Write-Host "  Total Files Processed: $totalProcessed" -ForegroundColor White
        Write-Host "  ✓ Successfully Processed: $totalSucceeded" -ForegroundColor Green
        Write-Host "  ✗ Failed: $totalFailed" -ForegroundColor Red
        if ($totalSkipped -gt 0) {
            Write-Host "  ⚡ Skipped: $totalSkipped" -ForegroundColor Yellow
        }
        
        if ($totalSucceeded + $totalFailed -gt 0) {
            $successRate = [math]::Round(($totalSucceeded / ($totalSucceeded + $totalFailed)) * 100, 2)
            Write-Host "  📈 Success Rate: $successRate%" -ForegroundColor Cyan
        }
    } else {
        Write-Host "No files were processed in this execution." -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Log -Message "Script execution completed at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') UTC" -Level "END" -Color Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "THEMIS SCRIPT EXECUTION COMPLETED" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
}

# ✅ GENERATE FINAL REPORTS
try {
    Write-Host ""
    Write-Log -Message "=== GENERATING FINAL REPORTS ===" -Level "INFO" -Color Magenta
    
    # Collect all phase data
    $allPhaseData = @{}
    if ($global:PhaseResults) {
        foreach ($phase in $global:PhaseResults.Keys) {
            $allPhaseData[$phase] = $global:PhaseResults[$phase]
        }
    }
    
    # Generate comprehensive reports
    Generate-PhaseReports -AllPhaseData $allPhaseData
    
    Write-Log -Message "=== REPORT GENERATION COMPLETED ===" -Level "SUCCESS" -Color Green
    Write-Host ""
    
} catch {
    Write-Log -Message "Error during report generation: $_" -Level "ERROR" -Color Red
}

# ✅ FINAL SUMMARY WITH PROPER NULL CHECKS
Write-Host ""
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host "           THEMIS SCRIPT EXECUTION COMPLETE    " -ForegroundColor Magenta  
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host ""

# Show final download/upload summaries if they exist
if ($global:DownloadResults -and $global:DownloadResults.Count -gt 0) {
    $downloadStats = @($global:DownloadResults.ToArray())
    $downloadSuccess = ($downloadStats | Where-Object { $_.Status -eq "Success" }).Count
    $downloadFailed = ($downloadStats | Where-Object { $_.Status -eq "Failed" }).Count
    Write-Host "📥 DOWNLOAD SUMMARY: $downloadSuccess succeeded, $downloadFailed failed" -ForegroundColor Cyan
}

if ($global:UploadResults -and $global:UploadResults.Count -gt 0) {
    $uploadStats = @($global:UploadResults.ToArray())
    $uploadSuccess = ($uploadStats | Where-Object { $_.Status -eq "Success" }).Count
    $uploadFailed = ($uploadStats | Where-Object { $_.Status -eq "Failed" }).Count
    Write-Host "📤 UPLOAD SUMMARY: $uploadSuccess succeeded, $uploadFailed failed" -ForegroundColor Cyan
}

Write-Host ""
if ($reportsDir) {
    Write-Host "📊 Check the generated HTML reports in: $reportsDir" -ForegroundColor Yellow
}
if ($errorDir) {
    Write-Host "📋 Check error files (if any) in: $errorDir" -ForegroundColor Yellow
}
Write-Host ""

# ✅ Show available files in directories if they exist
try {
    if ($reportsDir -and (Test-Path $reportsDir)) {
        $reportFiles = Get-ChildItem -Path $reportsDir -Filter "*.html" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
        if ($reportFiles.Count -gt 0) {
            Write-Host "📄 Recent HTML Reports:" -ForegroundColor Green
            foreach ($file in $reportFiles) {
                Write-Host "  • $($file.Name)" -ForegroundColor DarkGreen
            }
            Write-Host ""
        }
    }
    
    if ($errorDir -and (Test-Path $errorDir)) {
        $errorFiles = Get-ChildItem -Path $errorDir -Filter "*errors*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
        if ($errorFiles.Count -gt 0) {
            Write-Host "⚠️  Recent Error Files:" -ForegroundColor Yellow
            foreach ($file in $errorFiles) {
                Write-Host "  • $($file.Name)" -ForegroundColor DarkYellow
            }
            Write-Host ""
        }
        
        $retryFiles = Get-ChildItem -Path $errorDir -Filter "*retry*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
        if ($retryFiles.Count -gt 0) {
            Write-Host "🔄 Recent Retry Files:" -ForegroundColor Cyan
            foreach ($file in $retryFiles) {
                Write-Host "  • $($file.Name) (use with -RetryMode)" -ForegroundColor DarkCyan
            }
            Write-Host ""
        }
    }
} catch {
    # Ignore errors in file listing
}

# ================================================================================================
# STOP TRANSCRIPT LOGGING - ADD THIS AT THE VERY END
# ================================================================================================

try {
    Stop-Transcript
    Write-Host "📝 Console transcript saved to: $transcriptFile" -ForegroundColor Green
} catch {
    # Transcript might not be running
}

exit 0
