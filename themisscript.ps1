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
    $downloaded = 0
    $failed = 0
    $filtered = 0
    $startTime = Get-Date
    
    # ✅ ADD GRACEFUL SHUTDOWN VARIABLES
    $runspacePool = $null
    $downloadJobs = @()
    
    try {
        Write-Log -Message "==== START PHASE: Phase2-DownloadToLocal ====" -Level "PHASE" -Color Magenta
        
        $modeText = if ($RetryMode) { "RETRY MODE" } else { "NORMAL MODE" }
        Write-Log -Message "Phase 2: Parallel download with multithreading ($modeText)" -Level "INFO" -Color Green
        Write-Log -Message "Max Threads: $MaxThreads" -Level "INFO" -Color Cyan
        Write-Log -Message "Source: Cosmos VC" -Level "INFO" -Color Cyan
        Write-Log -Message "Destination: $localStagingDir" -Level "INFO" -Color Cyan
        Write-Log -Message "User: $user" -Level "INFO" -Color Cyan
        
        $fileTypeFilters = Parse-FileTypes -FileTypeString $FileType
        
        # Simple date filtering based on filename patterns if DaysBack is specified
        $dateFilterActive = $DaysBack -gt 0 -and -not $RetryMode
        $cutoffDate = if ($dateFilterActive) { 
            $cutoff = (Get-Date).AddDays(-$DaysBack)
            Write-Log -Message "DaysBack filtering: $DaysBack days (files newer than $($cutoff.ToString('yyyy-MM-dd')))" -Level "INFO" -Color Yellow
            $cutoff
        } else { 
            $filterText = if ($RetryMode) { "RETRY MODE - all error files will be processed" } else { "DaysBack filtering: DISABLED - downloading all files" }
            Write-Log -Message $filterText -Level "INFO" -Color Green
            [DateTime]::MinValue 
        }
        
        Write-Log -Message "FileType specified: $($fileTypeFilters -join ',')" -Level "INFO" -Color DarkGreen
        
        $allDownloads = @()
        
        if ($RetryMode -and -not [string]::IsNullOrEmpty($ErrorFile)) {
            Write-Log -Message "RETRY MODE: Loading files from error file..." -Level "INFO" -Color Magenta
            $retryFiles = Load-ErrorFileForRetry -ErrorFilePath $ErrorFile
            
            foreach ($retryFile in $retryFiles) {
                if ($retryFile.VcUrl -ne "LOCAL_FILE") {
                    $localSubDir = Join-Path $localStagingDir $retryFile.RelativePath.TrimEnd('/')
                    if (!(Test-Path $localSubDir)) {
                        New-Item -ItemType Directory -Path $localSubDir -Force | Out-Null
                    }
                    
                    $allDownloads += [PSCustomObject]@{
                        VcUrl = $retryFile.VcUrl
                        FileName = $retryFile.FileName
                        LocalPath = Join-Path $localSubDir $retryFile.FileName
                        RelativePath = $retryFile.RelativePath
                        CreationTime = $retryFile.CreationTime
                        OriginalSize = $retryFile.Size
                        OriginalError = $retryFile.OriginalError
                        Status = $null
                        Size = $null
                        Time = $null
                        Details = $null
                    }
                }
            }
            
            Write-Log -Message "RETRY MODE: Loaded $($allDownloads.Count) files for retry" -Level "SUCCESS" -Color Green
            
        } else {
            $fileLists = @()
            
            if (-not [string]::IsNullOrEmpty($InputFile)) {
                $inputPath = if (Test-Path $InputFile) { $InputFile } else { Join-Path $listDir $InputFile }
                if (Test-Path $inputPath) { $fileLists += $inputPath }
            } else {
                # Ensure directoryConfigs exists
                if (-not $directoryConfigs) {
                    $directoryConfigs = @(
                        @{ Type = "V1Daily"; Path = "V1/Daily/" },
                        @{ Type = "V2Daily"; Path = "V2/Daily/" },
                        @{ Type = "V1Monitor"; Path = "V1/Daily/Monitor/" },
                        @{ Type = "V2Monitor"; Path = "V2/Daily/Monitor/" },
                        @{ Type = "Count7511"; Path = "Counts/Count7511/Aggregates/" },
                        @{ Type = "Count7513"; Path = "Counts/Count7513/Aggregates/" },
                        @{ Type = "Count7515"; Path = "Counts/Count7515/Aggregates/" }
                    )
                }
                
                foreach ($config in $directoryConfigs) {
                    if ($fileTypeFilters -notcontains $config.Type) { continue }
                    $listFile = "$listDir\$($config.Type)_vc_listall.txt"
                    if (Test-Path $listFile) { $fileLists += $listFile }
                }
            }
            
            Write-Log -Message "Processing files from $($fileLists.Count) list files..." -Level "INFO" -Color Cyan
            
            foreach ($listFile in $fileLists) {
                if ($global:CleanupInProgress) { break }
                
                Write-Log -Message "Processing: $(Split-Path $listFile -Leaf)" -Level "INFO" -Color DarkCyan
                $entries = Get-Content $listFile | Where-Object { $_.Trim() -ne "" }
                
                Write-Log -Message "  Found $($entries.Count) entries in list file" -Level "INFO" -Color DarkGreen
                
                foreach ($entry in $entries) {
                    $parts = $entry -split "\|"
                    if ($parts.Length -ge 4) {
                        $vcUrl = $parts[0].Trim()
                        $fileName = $parts[1].Trim()
                        $relativePath = $parts[2].Trim()
                        $extension = $parts[3].Trim()
                        $creationTimeStr = if ($parts.Length -ge 5) { $parts[4].Trim() } else { "Unknown" }
                        
                        # Simple filename-based date filtering
                        if ($dateFilterActive) {
                            $shouldFilter = $false
                            
                            # Try to extract date from filename patterns like YYYYMMDD
                            if ($fileName -match "(\d{8})") {
                                $dateMatch = $matches[1]
                                try {
                                    $fileDate = [DateTime]::ParseExact($dateMatch, "yyyyMMdd", $null)
                                    if ($fileDate -lt $cutoffDate) {
                                        $shouldFilter = $true
                                        $filtered++
                                        Write-Log -Message "  SKIPPED: $fileName - File older than $DaysBack days cutoff ($($fileDate.ToString('yyyy-MM-dd')))" -Level "WARN" -Color Yellow
                                    }
                                } catch {
                                    Write-Log -Message "    Warning: Could not parse date from filename: $fileName" -Level "WARN" -Color Yellow
                                }
                            }
                            
                            if ($shouldFilter) {
                                continue
                            }
                        }
                        
                        $localSubDir = Join-Path $localStagingDir $relativePath.TrimEnd('/')
                        if (!(Test-Path $localSubDir)) {
                            New-Item -ItemType Directory -Path $localSubDir -Force | Out-Null
                        }
                        
                        $allDownloads += [PSCustomObject]@{
                            VcUrl = $vcUrl
                            FileName = $fileName
                            LocalPath = Join-Path $localSubDir $fileName
                            RelativePath = $relativePath
                            CreationTime = $creationTimeStr
                            OriginalSize = if ($parts.Length -ge 6) { $parts[5] } else { "Unknown" }
                            OriginalError = $null
                            Status = $null
                            Size = $null
                            Time = $null
                            Details = $null
                        }
                        
                        Write-Log -Message "  Queued: $fileName" -Level "DEBUG" -Color DarkGray
                    } else {
                        Write-Log -Message "    Warning: Skipping malformed entry: $entry" -Level "WARN" -Color Yellow
                    }
                }
                
                Write-Log -Message "  After filtering: $($allDownloads.Count) files queued for download, $filtered filtered" -Level "INFO" -Color Green
            }
        }
        
        $totalFiles = $allDownloads.Count
        $filterText = if ($RetryMode) { "(Retry files)" } else { "(Filtered by filename date: $filtered)" }
        Write-Log -Message "Total files to download: $totalFiles $filterText" -Level "INFO" -Color Green
        
        if ($totalFiles -eq 0) {
            Write-Log -Message "No files found for download after filtering" -Level "WARN" -Color Yellow
            return @{ Downloaded = 0; Failed = 0; Filtered = $filtered; Error = $null }
        }
        
        # ✅ PARALLEL MULTITHREADED DOWNLOAD
        Write-Log -Message "Starting parallel download with $MaxThreads threads..." -Level "INFO" -Color Magenta
        
        # Thread-safe collections for results
        $syncHashtable = [System.Collections.Hashtable]::Synchronized(@{})
        $lockObject = [System.Object]::new()
        
        # Create runspace pool
        $runspacePool = [runspacefactory]::CreateRunspacePool(1, $MaxThreads)
        $runspacePool.Open()
        
        # ✅ Download script block
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
                    
                    # Fix error message display
                    if ($output -is [array]) {
                        $errorMsg = ($output | Where-Object { $_ -and $_.ToString().Trim() } | ForEach-Object { $_.ToString().Trim() }) -join "; "
                    } elseif ($output) {
                        $errorMsg = $output.ToString().Trim()
                    } else {
                        $errorMsg = "Download failed with exit code $LASTEXITCODE"
                    }
                    
                    $download.Details = $errorMsg
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
                $download.Details = "Exception: $($_.Exception.Message)"
                
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
        
        # Initialize sync hashtable
        $syncHashtable.Results = [System.Collections.Generic.List[PSObject]]::new()
        $syncHashtable.Downloaded = 0
        $syncHashtable.Failed = 0
        
        # Create and start download jobs
        $downloadJobs = @()
        foreach ($download in $allDownloads) {
            # ✅ CHECK FOR CLEANUP SIGNAL
            if ($global:CleanupInProgress) {
                Write-Log -Message "Cleanup signal received, stopping job creation..." -Level "WARN" -Color Yellow
                break
            }
            
            $powerShell = [powershell]::Create()
            $powerShell.RunspacePool = $runspacePool
            $powerShell.AddScript($downloadScriptBlock).AddParameter("download", $download).AddParameter("syncHash", $syncHashtable).AddParameter("lockObj", $lockObject).AddParameter("user", $user).AddParameter("useMSAL", $UseMSAL).AddParameter("tokenFile", $global:TokenFilePath).AddParameter("isRetryMode", $RetryMode) | Out-Null
            
            $downloadJobs += [PSCustomObject]@{
                PowerShell = $powerShell
                Handle = $powerShell.BeginInvoke()
                Download = $download
                IsCompleted = $false
            }
        }
        
        # Monitor progress with cleanup handling
        $totalJobs = $downloadJobs.Count
        $completedJobs = 0
        
        Write-Log -Message "Monitoring $totalJobs parallel download jobs..." -Level "INFO" -Color Cyan
        
        while ($completedJobs -lt $totalJobs -and -not $global:CleanupInProgress) {
            Start-Sleep -Milliseconds 500
            
            $newlyCompleted = 0
            foreach ($job in $downloadJobs) {
                if ($job.Handle.IsCompleted -and -not $job.IsCompleted) {
                    try {
                        $result = $job.PowerShell.EndInvoke($job.Handle)
                        $job.IsCompleted = $true
                        $completedJobs++
                        $newlyCompleted++
                        
                        # Log individual completion
                        if ($result -and $result.Status) {
                            if ($result.Status -eq "Success") {
                                Write-Log -Message "  SUCCESS: $($result.FileName) ($($result.Size) in $($result.Time))" -Level "SUCCESS" -Color Green
                            } else {
                                Write-Log -Message "  FAILED: $($result.FileName)" -Level "ERROR" -Color Red
                                if ($result.Details) {
                                    Write-Log -Message "    Error: $($result.Details)" -Level "ERROR" -Color Red
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
            
            if ($newlyCompleted -gt 0) {
                $progressPercent = [math]::Round(($completedJobs / $totalJobs) * 100, 1)
                Write-Log -Message "Download Progress: $completedJobs/$totalJobs completed ($progressPercent%)" -Level "INFO" -Color Cyan
            }
        }
        
        # ✅ GRACEFUL CLEANUP WHEN INTERRUPTED
        if ($global:CleanupInProgress) {
            Write-Log -Message "Cleanup signal received, stopping remaining download jobs..." -Level "WARN" -Color Yellow
            
            # Cancel remaining jobs
            foreach ($job in $downloadJobs) {
                if (-not $job.IsCompleted) {
                    try {
                        $job.PowerShell.Stop()
                        $job.PowerShell.Dispose()
                        $job.IsCompleted = $true
                    } catch {
                        # Ignore disposal errors during cleanup
                    }
                }
            }
        }
        
        # Get final results
        $downloaded = $syncHashtable.Downloaded
        $failed = $syncHashtable.Failed
        $allDownloads = $syncHashtable.Results.ToArray()
        
        Write-Log -Message "Parallel Download Results: $downloaded downloaded, $failed failed, $filtered filtered" -Level "INFO" -Color Cyan
        
        # ✅ GENERATE REPORT WITH UPDATED STATUS (maintaining existing flow)
        Write-Log -Message "Generating download report..." -Level "INFO" -Color Cyan
        try {
            if ($allDownloads.Count -gt 0) {
                # Convert to existing report format to maintain compatibility
                $global:DownloadResults = [System.Collections.Generic.List[PSObject]]::new()
                
                foreach ($download in $allDownloads) {
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
                
                # Save error files (existing functionality)
                Save-ErrorFiles -OperationType "Download" -Results $global:DownloadResults
                
                Write-Log -Message "Download results processed for existing reporting flow" -Level "SUCCESS" -Color Green
            } else {
                Write-Log -Message "No download results to report" -Level "WARN" -Color Yellow
            }
        } catch {
            Write-Log -Message "Error generating report: $_" -Level "ERROR" -Color Red
        }
        
        return @{
            Downloaded = $downloaded
            Failed = $failed
            Filtered = $filtered
            Error = $null
        }
        
    } catch {
        $errorMsg = "Error in Phase 2: $($_.Exception.Message)"
        Write-Log -Message $errorMsg -Level "ERROR" -Color Red
        return @{ Downloaded = 0; Failed = 0; Filtered = $filtered; Error = $errorMsg }
        
    } finally {
        # ✅ GUARANTEED CLEANUP
        Write-Log -Message "Cleaning up download resources..." -Level "INFO" -Color Yellow
        
        # Dispose all remaining PowerShell objects
        if ($downloadJobs) {
            foreach ($job in $downloadJobs) {
                try {
                    if ($job.PowerShell -and -not $job.IsCompleted) {
                        $job.PowerShell.Stop()
                    }
                    if ($job.PowerShell) {
                        $job.PowerShell.Dispose()
                    }
                } catch {
                    # Ignore disposal errors during cleanup
                }
            }
        }
        
        # Close and dispose runspace pool
        if ($runspacePool) {
            try {
                $runspacePool.Close()
                $runspacePool.Dispose()
                Write-Log -Message "Runspace pool cleaned up successfully" -Level "INFO" -Color Green
            } catch {
                Write-Log -Message "Error cleaning up runspace pool: $($_.Exception.Message)" -Level "WARN" -Color Yellow
            }
        }
        
        # ✅ DOWNLOAD VERIFICATION - Check if all expected files were downloaded
        Write-Log -Message "=== DOWNLOAD VERIFICATION ===" -Level "INFO" -Color Cyan
        $expectedFiles = $allDownloads.Count
        $successfulDownloads = $allDownloads | Where-Object { $_.Status -eq "Success" }
        $actualDownloadedFiles = @()
        
        foreach ($download in $successfulDownloads) {
            if (Test-Path $download.LocalPath) {
                $fileInfo = Get-Item $download.LocalPath -ErrorAction SilentlyContinue
                if ($fileInfo -and $fileInfo.Length -gt 0) {
                    $actualDownloadedFiles += $download
                }
            }
        }
        
        $actualCount = $actualDownloadedFiles.Count
        $missingFiles = $allDownloads | Where-Object { 
            $_.Status -ne "Success" -or -not (Test-Path $_.LocalPath) -or (Get-Item $_.LocalPath -ErrorAction SilentlyContinue).Length -eq 0 
        }
        
        Write-Log -Message "Expected files to download: $expectedFiles" -Level "INFO" -Color White
        Write-Log -Message "Successfully downloaded: $actualCount" -Level "INFO" -Color Green
        Write-Log -Message "Missing/Failed files: $($missingFiles.Count)" -Level "INFO" -Color $(if($missingFiles.Count -eq 0) {"Green"} else {"Yellow"})
        
        if ($missingFiles.Count -gt 0) {
            Write-Log -Message "Missing files details:" -Level "WARN" -Color Yellow
            foreach ($missing in ($missingFiles | Select-Object -First 10)) {
                Write-Log -Message "  - $($missing.FileName): $($missing.Details)" -Level "WARN" -Color Yellow
            }
            if ($missingFiles.Count -gt 10) {
                Write-Log -Message "  ... and $($missingFiles.Count - 10) more files" -Level "WARN" -Color Yellow
            }
        }
        
        $downloadCompletionRate = if ($expectedFiles -gt 0) { [math]::Round(($actualCount / $expectedFiles) * 100, 1) } else { 0 }
        Write-Log -Message "Download completion rate: $downloadCompletionRate%" -Level "INFO" -Color $(if($downloadCompletionRate -eq 100) {"Green"} elseif($downloadCompletionRate -ge 80) {"Yellow"} else {"Red"})
        Write-Log -Message "=== END DOWNLOAD VERIFICATION ===" -Level "INFO" -Color Cyan
        
        $duration = (Get-Date) - $startTime
        Write-Log -Message "==== END PHASE: Phase2-DownloadToLocal | Duration: $($duration.ToString('hh\:mm\:ss')) ====" -Level "PHASE" -Color Magenta
    }
}

# ================================================================================================
# COMPLETE Phase3-UploadToDestination FUNCTION WITH UPLOAD FUNCTIONALITY
# Current Date and Time (UTC): 2025-08-12 05:55:47
# Current User: varadharajaan
# ================================================================================================

function Phase3-UploadToDestination {
    $uploaded = 0
    $failed = 0
    $skipped = 0
    $startTime = Get-Date
    
    # ✅ ADD GRACEFUL SHUTDOWN VARIABLES
    $runspacePool = $null
    $uploadJobs = @()
    
    try {
        Write-Log -Message "==== START PHASE: Phase3-UploadToDestination ====" -Level "PHASE" -Color Magenta
        
        # Fix missing destination - USE YOUR CORRECT PATHS
        if ([string]::IsNullOrEmpty($destination_https)) {
            if ($Destination -and $Destination.ToLower() -eq "prod") {
                $destination_https = "vc://cosmos08/bingads.algo.adquality/shares/bingads.algo.rap2/PriamBackup/ThemisINTL/"
            } else {
                $destination_https = "vc://cosmos08/bingads.algo.adquality/local/users/vdamotharan/ThemisINTL/"
            }
            Write-Log -Message "Destination set to: $destination_https" -Level "INFO" -Color Green
        }
        
        Write-Log -Message "Phase 3: Parallel Upload to Cosmos destination" -Level "INFO" -Color Green
        Write-Log -Message "Max Threads: $MaxThreads" -Level "INFO" -Color Cyan
        Write-Log -Message "Source: $localStagingDir" -Level "INFO" -Color Cyan
        Write-Log -Message "Destination: $destination_https" -Level "INFO" -Color Cyan
        Write-Log -Message "User: vdamotharan@microsoft.com" -Level "INFO" -Color Cyan
        
        # Show DaysBack filtering info
        if ($DaysBack -and $DaysBack -gt 0) {
            $cutoffDate = (Get-Date).AddDays(-$DaysBack)
            Write-Log -Message "DaysBack filtering: $DaysBack days (files newer than $($cutoffDate.ToString('yyyy-MM-dd')))" -Level "INFO" -Color Yellow
        } else {
            Write-Log -Message "DaysBack filtering: DISABLED - uploading all files" -Level "INFO" -Color Green
        }
        
        # Fix missing fileTypeFilters
        if (-not $fileTypeFilters -or $fileTypeFilters.Count -eq 0) {
            if ($FileType) {
                $fileTypeFilters = @($FileType)
            } else {
                $fileTypeFilters = @("V1Daily")
            }
        }
        
        Write-Log -Message "FileType specified: $($fileTypeFilters -join ',')" -Level "INFO" -Color DarkGreen
        
        # Ensure directoryConfigs exists
        if (-not $directoryConfigs) {
            $directoryConfigs = @(
                @{ Type = "V1Daily"; Path = "V1/Daily/" },
                @{ Type = "V2Daily"; Path = "V2/Daily/" },
                @{ Type = "V1Monitor"; Path = "V1/Daily/Monitor/" },
                @{ Type = "V2Monitor"; Path = "V2/Daily/Monitor/" },
                @{ Type = "Count7511"; Path = "Counts/Count7511/Aggregates/" },
                @{ Type = "Count7513"; Path = "Counts/Count7513/Aggregates/" },
                @{ Type = "Count7515"; Path = "Counts/Count7515/Aggregates/" }
            )
        }
        
        $allUploads = @()
        
        # ✅ Get existing files from destination for DaysBack filtering (SKIP FOR NOW TO SPEED UP)
        $existingFilesMap = @{}
        if ($DaysBack -and $DaysBack -gt 0) {
            Write-Log -Message "Checking existing files in destination for DaysBack filtering..." -Level "INFO" -Color Cyan
            
            foreach ($config in $directoryConfigs) {
                if ($fileTypeFilters -notcontains $config.Type) { continue }
                
                $remotePath = $destination_https + $config.Path.TrimEnd('/')
                $remotePath = $remotePath -replace "(?<!:)//+", "/"
                
                try {
                    Write-Log -Message "  Listing files in: $remotePath" -Level "DEBUG" -Color DarkGray
                    $listCommand = "scope.exe dir `"$remotePath`" -on UseCachedCredentials -u vdamotharan@microsoft.com"
                    $listOutput = Invoke-Expression $listCommand
                    
                    if ($LASTEXITCODE -eq 0 -and $listOutput) {
                        # Parse the output to extract filenames and dates
                        $lines = $listOutput -split "`n" | Where-Object { $_ -and $_ -notmatch "Directory of" -and $_ -notmatch "^\s*$" }
                        
                        foreach ($line in $lines) {
                            # Parse scope dir output format: typically shows filename and modification date
                            if ($line -match '(\d{8}_\d{4}_\w+.*\.ss)') {
                                $fileName = $matches[1]
                                
                                # Extract date from filename (format: YYYYMMDD_HHMM_...)
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
            if ($fileTypeFilters -notcontains $config.Type) { continue }
            
            $configPath = $config.Path.TrimEnd('/')
            $localSubDir = Join-Path $localStagingDir $configPath
            
            if (Test-Path $localSubDir) {
                Write-Log -Message "Scanning for $($config.Type) files in: $localSubDir" -Level "INFO" -Color DarkCyan
                
                # Get direct files only (no subdirectories)
                $localFiles = Get-ChildItem -Path $localSubDir -File | Where-Object {
                    $_.Name -notmatch "^\..*" -and $_.Length -gt 0
                }
                
                Write-Log -Message "  Found $($localFiles.Count) total files in $($config.Type)" -Level "INFO" -Color DarkGreen
                
                # ✅ Apply DaysBack filtering
                $filteredFiles = @()
                foreach ($file in $localFiles) {
                    if (-not $file -or -not $file.Name) { continue }
                    
                    $shouldUpload = $true
                    $skipReason = ""
                    
                    # Apply DaysBack filtering if specified
                    if ($DaysBack -and $DaysBack -gt 0) {
                        # Extract date from local filename
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
                                    # Check if newer version exists in destination
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
                    # Proper URL construction
                    $relativePath = $config.Path
                    if (-not $relativePath.EndsWith('/')) { $relativePath += '/' }
                    
                    $destinationUrl = $destination_https + $relativePath + $file.Name
                    # Clean up any double slashes except after vc://
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
        
        if ($allUploads.Count -eq 0) {
            Write-Log -Message "No files found for upload after filtering" -Level "WARN" -Color Yellow
            return @{ Uploaded = 0; Failed = 0; Skipped = $skipped; Error = $null }
        }
        
        Write-Log -Message "Total files to upload: $($allUploads.Count)" -Level "INFO" -Color Green
        
        # ✅ FIXED PARALLEL MULTITHREADED UPLOAD WITH GRACEFUL SHUTDOWN
        Write-Log -Message "Starting parallel upload with $MaxThreads threads..." -Level "INFO" -Color Magenta
        
        # Thread-safe collections for results
        $syncHashtable = [System.Collections.Hashtable]::Synchronized(@{})
        $lockObject = [System.Object]::new()
        
        # Create runspace pool
        $runspacePool = [runspacefactory]::CreateRunspacePool(1, $MaxThreads)
        $runspacePool.Open()
        
        # ✅ FIXED Upload script block with correct expiration syntax
        $uploadScriptBlock = {
            param($upload, $syncHash, $lockObj, $expiry_days)
            
            try {
                $startTime = Get-Date
                
                # BUILD SCOPE UPLOAD COMMAND
                $localPath = $upload.LocalPath
                $destinationUrl = $upload.DestinationUrl
                
                if (-not (Test-Path $localPath)) {
                    throw "Local file not found: $localPath"
                }

                $fileFlag = if ($upload.FileName.EndsWith('.ss')) { '-binary' } else { '-text' }
                
                $command = "scope.exe copy `"$localPath`" `"$destinationUrl`" -expirationtime $expiry_days  $fileFlag -on UseAadAuthentication -u vdamotharan@microsoft.com"
                
                # EXECUTE UPLOAD
                $result = Invoke-Expression $command 2>&1
                $exitCode = $LASTEXITCODE
                
                $endTime = Get-Date
                $duration = ($endTime - $startTime).TotalSeconds
                
                if ($exitCode -eq 0) {
                    $fileSize = (Get-Item $localPath).Length
                    $sizeInMB = [math]::Round($fileSize / 1MB, 2)
                    
                    $upload.Status = "Success"
                    $upload.Size = "$sizeInMB MB"
                    $upload.Time = "$([math]::Round($duration, 2))s"
                    $upload.Details = "Uploaded successfully"
                } else {
                    $upload.Status = "Failed"
                    $upload.Size = "0 MB"
                    $upload.Time = "$([math]::Round($duration, 2))s"
                    $upload.Details = "Upload failed: $result"
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
                $upload.Details = "Exception: $($_.Exception.Message)"
                
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
        # Initialize sync hashtable
        $syncHashtable.Results = [System.Collections.Generic.List[PSObject]]::new()
        $syncHashtable.Uploaded = 0
        $syncHashtable.Failed = 0
        
        # Create and start upload jobs
        $uploadJobs = @()
        foreach ($upload in $allUploads) {
            # ✅ CHECK FOR CLEANUP SIGNAL
            if ($global:CleanupInProgress) {
                Write-Log -Message "Cleanup signal received, stopping job creation..." -Level "WARN" -Color Yellow
                break
            }
            
            $powerShell = [powershell]::Create()
            $powerShell.RunspacePool = $runspacePool
            $powerShell.AddScript($uploadScriptBlock).AddParameter("upload", $upload).AddParameter("syncHash", $syncHashtable).AddParameter("lockObj", $lockObject).AddParameter("expiry_days", $expiry_days) | Out-Null
            
            $uploadJobs += [PSCustomObject]@{
                PowerShell = $powerShell
                Handle = $powerShell.BeginInvoke()
                Upload = $upload
                IsCompleted = $false
            }
        }
        
        # Monitor progress with cleanup handling
        $totalJobs = $uploadJobs.Count
        $completedJobs = 0
        
        Write-Log -Message "Monitoring $totalJobs parallel upload jobs..." -Level "INFO" -Color Cyan
        
        while ($completedJobs -lt $totalJobs -and -not $global:CleanupInProgress) {
            Start-Sleep -Milliseconds 500
            
            $newlyCompleted = 0
            foreach ($job in $uploadJobs) {
                if ($job.Handle.IsCompleted -and -not $job.IsCompleted) {
                    try {
                        $result = $job.PowerShell.EndInvoke($job.Handle)
                        $job.IsCompleted = $true
                        $completedJobs++
                        $newlyCompleted++
                        
                        # Log individual completion
                        if ($result -and $result.Status) {
                            if ($result.Status -eq "Success") {
                                Write-Log -Message "  SUCCESS: $($result.FileName) ($($result.Size) in $($result.Time))" -Level "SUCCESS" -Color Green
                            } else {
                                Write-Log -Message "  FAILED: $($result.FileName)" -Level "ERROR" -Color Red
                                if ($result.Details) {
                                    Write-Log -Message "    Error: $($result.Details)" -Level "ERROR" -Color Red
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
            
            if ($newlyCompleted -gt 0) {
                $progressPercent = [math]::Round(($completedJobs / $totalJobs) * 100, 1)
                Write-Log -Message "Upload Progress: $completedJobs/$totalJobs completed ($progressPercent%)" -Level "INFO" -Color Cyan
            }
        }
        
        # ✅ GRACEFUL CLEANUP WHEN INTERRUPTED
        if ($global:CleanupInProgress) {
            Write-Log -Message "Cleanup signal received, stopping remaining upload jobs..." -Level "WARN" -Color Yellow
            
            # Cancel remaining jobs
            foreach ($job in $uploadJobs) {
                if (-not $job.IsCompleted) {
                    try {
                        $job.PowerShell.Stop()
                        $job.PowerShell.Dispose()
                        $job.IsCompleted = $true
                    } catch {
                        # Ignore disposal errors during cleanup
                    }
                }
            }
        }
        
        # Get final results
        $uploaded = $syncHashtable.Uploaded
        $failed = $syncHashtable.Failed
        $allUploads = $syncHashtable.Results.ToArray()
        
        Write-Log -Message "Parallel Upload Results: $uploaded uploaded, $failed failed, $skipped skipped" -Level "INFO" -Color Cyan
        
        # GENERATE REPORT WITH UPDATED STATUS
        Write-Log -Message "Generating upload report..." -Level "INFO" -Color Cyan
        try {
            if ($allUploads.Count -gt 0) {
                # Convert to report format with all tracked data
                $reportResults = $allUploads | ForEach-Object {
                    [PSCustomObject]@{
                        FileName = $_.FileName
                        Status = if ($_.Status) { $_.Status } else { "Unknown" }
                        Size = if ($_.Size) { $_.Size } else { "0 MB" }
                        Time = if ($_.Time) { $_.Time } else { "0s" }
                        VcUrl = $_.DestinationUrl
                        Details = if ($_.Details) { $_.Details } else { "No details available" }
                    }
                }
                
                $reportFile = Generate-HTMLReport -ReportType "Upload" -Results $reportResults
                if ($reportFile) {
                    Write-Log -Message "Upload report generated: $reportFile" -Level "SUCCESS" -Color Green
                } else {
                    Write-Log -Message "Failed to generate upload report" -Level "WARN" -Color Yellow
                }
            } else {
                Write-Log -Message "No upload results to report" -Level "WARN" -Color Yellow
            }
        } catch {
            Write-Log -Message "Error generating report: $_" -Level "ERROR" -Color Red
        }
        
        return @{
            Uploaded = $uploaded
            Failed = $failed
            Skipped = $skipped
            Error = $null
        }
        
    } catch {
        $errorMsg = "Error in Phase 3: $($_.Exception.Message)"
        Write-Log -Message $errorMsg -Level "ERROR" -Color Red
        return @{ Uploaded = 0; Failed = 0; Skipped = 0; Error = $errorMsg }
        
    } finally {
        # ✅ GUARANTEED CLEANUP
        Write-Log -Message "Cleaning up upload resources..." -Level "INFO" -Color Yellow
        
        # Dispose all remaining PowerShell objects
        if ($uploadJobs) {
            foreach ($job in $uploadJobs) {
                try {
                    if ($job.PowerShell -and -not $job.IsCompleted) {
                        $job.PowerShell.Stop()
                    }
                    if ($job.PowerShell) {
                        $job.PowerShell.Dispose()
                    }
                } catch {
                    # Ignore disposal errors during cleanup
                }
            }
        }
        
        # Close and dispose runspace pool
        if ($runspacePool) {
            try {
                $runspacePool.Close()
                $runspacePool.Dispose()
                Write-Log -Message "Runspace pool cleaned up successfully" -Level "INFO" -Color Green
            } catch {
                Write-Log -Message "Error cleaning up runspace pool: $($_.Exception.Message)" -Level "WARN" -Color Yellow
            }
        }
        
        # ✅ UPLOAD VERIFICATION - Check if all expected files were uploaded
        Write-Log -Message "=== UPLOAD VERIFICATION ===" -Level "INFO" -Color Cyan
        $expectedUploads = $allUploads.Count
        $successfulUploads = $allUploads | Where-Object { $_.Status -eq "Success" }
        $actualUploadedFiles = @()
        
        # Verify uploads by checking if the source files still exist and were marked as successful
        foreach ($upload in $successfulUploads) {
            if (Test-Path $upload.LocalPath) {
                $fileInfo = Get-Item $upload.LocalPath -ErrorAction SilentlyContinue
                if ($fileInfo -and $fileInfo.Length -gt 0) {
                    $actualUploadedFiles += $upload
                }
            }
        }
        
        $actualUploadCount = $actualUploadedFiles.Count
        $failedUploads = $allUploads | Where-Object { 
            $_.Status -ne "Success" -or -not (Test-Path $_.LocalPath) 
        }
        
        # Double-check local files are still present (they should be after upload)
        $localFilesPresent = @()
        foreach ($upload in $allUploads) {
            if (Test-Path $upload.LocalPath) {
                $localFilesPresent += $upload
            }
        }
        
        Write-Log -Message "Expected files to upload: $expectedUploads" -Level "INFO" -Color White
        Write-Log -Message "Successfully uploaded: $actualUploadCount" -Level "INFO" -Color Green
        Write-Log -Message "Failed uploads: $($failedUploads.Count)" -Level "INFO" -Color $(if($failedUploads.Count -eq 0) {"Green"} else {"Yellow"})
        Write-Log -Message "Local source files still present: $($localFilesPresent.Count)" -Level "INFO" -Color Green
        
        if ($failedUploads.Count -gt 0) {
            Write-Log -Message "Failed upload details:" -Level "WARN" -Color Yellow
            foreach ($failed in ($failedUploads | Select-Object -First 10)) {
                Write-Log -Message "  - $($failed.FileName): $($failed.Details)" -Level "WARN" -Color Yellow
            }
            if ($failedUploads.Count -gt 10) {
                Write-Log -Message "  ... and $($failedUploads.Count - 10) more files" -Level "WARN" -Color Yellow
            }
        }
        
        # Check if any local files are missing (shouldn't happen after upload)
        $missingLocalFiles = $allUploads | Where-Object { -not (Test-Path $_.LocalPath) }
        if ($missingLocalFiles.Count -gt 0) {
            Write-Log -Message "WARNING: $($missingLocalFiles.Count) local source files are missing after upload!" -Level "ERROR" -Color Red
        }
        
        $uploadCompletionRate = if ($expectedUploads -gt 0) { [math]::Round(($actualUploadCount / $expectedUploads) * 100, 1) } else { 0 }
        Write-Log -Message "Upload completion rate: $uploadCompletionRate%" -Level "INFO" -Color $(if($uploadCompletionRate -eq 100) {"Green"} elseif($uploadCompletionRate -ge 80) {"Yellow"} else {"Red"})
        Write-Log -Message "=== END UPLOAD VERIFICATION ===" -Level "INFO" -Color Cyan
        
        $duration = (Get-Date) - $startTime
        Write-Log -Message "==== END PHASE: Phase3-UploadToDestination | Duration: $($duration.ToString('hh\:mm\:ss')) ====" -Level "PHASE" -Color Magenta
    }
}


# ================================================================================================
# UPLOAD FAILURE REPORTING FUNCTIONS
# ================================================================================================

function Show-ManualUploadFailureReport {
    param([string]$OperationType = "UPLOAD")
    
    $allResults = @($global:UploadResults.ToArray())
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
        Write-Host "Recent upload failures ($($recentFailures.Count) shown):" -ForegroundColor Yellow
        
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

function Show-FinalUploadFailureReport {
    param([string]$OperationType = "UPLOAD")
    
    $allResults = @($global:UploadResults.ToArray())
    $allFailures = $allResults | Where-Object { $_.Status -eq "Failed" }
    
    if ($allFailures.Count -gt 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "FINAL $OperationType FAILURE SUMMARY" -ForegroundColor Red  
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "Total failures: $($allFailures.Count)" -ForegroundColor Yellow
        
        # Group failures by error type
        $errorGroups = $allFailures | Group-Object { 
            if ($_.Details -match "Access is denied") { "Access Denied" }
            elseif ($_.Details -match "authentication") { "Authentication Error" }
            elseif ($_.Details -match "not found") { "File Not Found" }
            elseif ($_.Details -match "timeout") { "Timeout" }
            else { "Other Error" }
        }
        
        foreach ($group in $errorGroups) {
            Write-Host "  $($group.Name): $($group.Count) files" -ForegroundColor Yellow
        }
        
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
    }
}

function Save-UploadErrorFiles {
    param(
        [string]$OperationType,
        [object]$Results
    )
    
    try {
        $allResults = @($Results.ToArray())
        $failures = $allResults | Where-Object { $_.Status -eq "Failed" }
        
        if ($failures.Count -gt 0) {
            $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $errorFile = Join-Path $errorDir "$OperationType-errors_$timestamp.csv"
            
            $failures | ForEach-Object {
                [PSCustomObject]@{
                    FileName = $_.FileName
                    LocalPath = $_.LocalPath
                    DestinationUrl = $_.DestinationUrl
                    RelativePath = $_.RelativePath
                    Size = $_.Size
                    Status = $_.Status
                    Details = $_.Details
                    Time = $_.Time
                }
            } | Export-Csv -Path $errorFile -NoTypeInformation -Encoding UTF8
            
            Write-Log -Message "Upload error file saved: $errorFile" -Level "INFO" -Color Yellow
            
            # Also save retry file
            $retryFile = Join-Path $errorDir "$OperationType-retry_$timestamp.csv"
            $failures | ForEach-Object {
                [PSCustomObject]@{
                    FileName = $_.FileName
                    VcUrl = "LOCAL_FILE"  # Mark as local file for upload retry
                    RelativePath = $_.RelativePath
                    CreationTime = "Unknown"
                    Size = $_.Size
                    OriginalError = $_.Details
                }
            } | Export-Csv -Path $retryFile -NoTypeInformation -Encoding UTF8
            
            Write-Log -Message "Upload retry file saved: $retryFile" -Level "INFO" -Color Yellow
        }
    } catch {
        Write-Log -Message "Error saving upload error files: $_" -Level "ERROR" -Color Red
    }
}

# ================================================================================================
# HTML REPORT GENERATION FUNCTIONS
# Current Date and Time (UTC): 2025-08-12 06:33:43
# Current User: varadharajaan
# ================================================================================================

function Generate-HTMLReport {
    param(
        [string]$ReportType,
        [array]$Results,
        [string]$CustomPath = ""
    )
    
    try {
        $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
        $utcTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")
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
        <h2>📊 Upload Statistics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">$totalFiles</div>
                <div class="stat-label">Total Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-number success">$successCount</div>
                <div class="stat-label">Successfully Uploaded</div>
            </div>
            <div class="stat-card">
                <div class="stat-number error">$failedCount</div>
                <div class="stat-label">Failed Uploads</div>
            </div>
            <div class="stat-card">
                <div class="stat-number warning">$skippedCount</div>
                <div class="stat-label">Skipped Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$([math]::Round($totalSize, 2)) MB</div>
                <div class="stat-label">Total Data Size</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$([math]::Round($totalTime, 1))s</div>
                <div class="stat-label">Total Upload Time</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">$successRate%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>
    </div>
"@

        # Upload results table
        if ($Results.Count -gt 0) {
            $html += @"
    <div class="section">
        <h2>📁 Upload Results</h2>
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
                    <th>🔗 Destination URL</th>
                    <th>📝 Details</th>
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
                
                $fileName = if ($result.FileName) { $result.FileName } else { "Unknown" }
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
                    <td class="details-cell" title="$details">$details</td>
                </tr>
"@
            }

            $html += @"
            </tbody>
        </table>
    </div>
"@
        }

        # Add JavaScript for filtering
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
            $downloadReport = Generate-HTMLReport -ReportType "Download" -Results $downloadResults -PhaseData $AllPhaseData
            Write-Log -Message "Download report generated: $downloadReport" -Level "SUCCESS" -Color Green
        }
        
        # Generate upload report if upload results exist
        if ($global:UploadResults -and $global:UploadResults.Count -gt 0) {
            $uploadResults = @($global:UploadResults.ToArray())
            $uploadReport = Generate-HTMLReport -ReportType "Upload" -Results $uploadResults -PhaseData $AllPhaseData
            Write-Log -Message "Upload report generated: $uploadReport" -Level "SUCCESS" -Color Green
        }
        
        # Generate overall summary report
        $allResults = @()
        if ($global:DownloadResults) { $allResults += @($global:DownloadResults.ToArray()) }
        if ($global:UploadResults) { $allResults += @($global:UploadResults.ToArray()) }
        
        if ($allResults.Count -gt 0) {
            $summaryReport = Generate-HTMLReport -ReportType "Summary" -Results $allResults -PhaseData $AllPhaseData
            Write-Log -Message "Summary report generated: $summaryReport" -Level "SUCCESS" -Color Green
        }
        
    } catch {
        Write-Log -Message "Error generating phase reports: $_" -Level "ERROR" -Color Red
    }
}



# ================================================================================================
# MAIN EXECUTION
# ================================================================================================
Write-Log -Message "THEMIS FILE MANAGEMENT SCRIPT - WITHOUT METADATA EXTRACTION" -Level "START" -Color Cyan
Write-Log -Message "Current Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') UTC" -Level "INFO" -Color Cyan
Write-Log -Message "Current User: varadharajaan" -Level "INFO" -Color Cyan

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
    } else {
        Write-Log -Message "Executing phases: $($requestedPhases -join ', ')" -Level "INFO" -Color Cyan
        
        foreach ($phaseNum in $requestedPhases) {
            if ($global:CleanupInProgress) { break }
            
            switch ($phaseNum) {
                "1" { Phase1-ListAllFiles }
                "2" { Phase2-DownloadToLocal }
                "3" { Phase3-UploadToDestination }
            }
        }
    }
} catch {
    Write-Log -Message "Fatal error: $_" -Level "ERROR" -Color Red
    Cleanup-Resources
} finally {
    if ($global:RunspacePools.Count -gt 0 -or $global:ActiveJobs.Count -gt 0 -or $global:TokenMonitorJob) {
        Write-Log -Message "Performing final cleanup..." -Level "INFO" -Color Yellow
        Cleanup-Resources
    }
}

if (-not $global:CleanupInProgress) {
    Write-Host ""
    Write-Log -Message "EXECUTION SUMMARY" -Level "SUMMARY" -Color Cyan
    foreach ($ps in $global:PhaseSummaries) {
        $dataStr = if ($ps.Data) { ($ps.Data.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', ' } else { "N/A" }
        Write-Host ("{0,-30} Duration={1,-12} Data={2}" -f $ps.Phase, $ps.Duration.ToString("hh\:mm\:ss"), $dataStr)
    }
    Write-Log -Message "SCRIPT COMPLETED SUCCESSFULLY" -Level "END" -Color Green
    Write-Log -Message "Reports available in: $reportDir" -Level "INFO" -Color Cyan
    
    if ($UseMSAL) {
        Write-Log -Message "MSAL token file cleaned up" -Level "INFO" -Color Cyan
    }
    
    Write-Log -Message "Error files (if any) available in: $errorDir" -Level "INFO" -Color Cyan
    
    # Show total script execution time
    $totalDuration = New-TimeSpan -Start $global:ScriptStart -End (Get-Date)
    Write-Log -Message "Total Script Duration: $($totalDuration.ToString('hh\:mm\:ss'))" -Level "INFO" -Color Green
    
    # Show final statistics
    if ($global:PhaseSummaries.Count -gt 0) {
        Write-Host ""
        Write-Log -Message "FINAL STATISTICS" -Level "SUMMARY" -Color Cyan
        
        $totalDownloaded = 0
        $totalFailed = 0
        $totalFiltered = 0
        
        foreach ($phase in $global:PhaseSummaries) {
            if ($phase.Data) {
                if ($phase.Data.Downloaded) { $totalDownloaded += $phase.Data.Downloaded }
                if ($phase.Data.Failed) { $totalFailed += $phase.Data.Failed }
                if ($phase.Data.Filtered) { $totalFiltered += $phase.Data.Filtered }
            }
        }
        
        if ($totalDownloaded + $totalFailed + $totalFiltered -gt 0) {
            Write-Host "Total Files Processed: $($totalDownloaded + $totalFailed + $totalFiltered)" -ForegroundColor White
            Write-Host "  ✓ Successfully Downloaded: $totalDownloaded" -ForegroundColor Green
            Write-Host "  ✗ Failed: $totalFailed" -ForegroundColor Red
            if ($totalFiltered -gt 0) {
                Write-Host "  ⚡ Filtered by Date: $totalFiltered" -ForegroundColor Yellow
            }
            
            if ($totalDownloaded + $totalFailed -gt 0) {
                $successRate = [math]::Round(($totalDownloaded / ($totalDownloaded + $totalFailed)) * 100, 2)
                Write-Host "  📊 Success Rate: $successRate%" -ForegroundColor Cyan
            }
        }
    }
    
    Write-Host ""
    Write-Log -Message "Script execution completed at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') UTC" -Level "END" -Color Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "THEMIS SCRIPT EXECUTION COMPLETED" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
}

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

# Final summary
Write-Host ""
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host "           THEMIS SCRIPT EXECUTION COMPLETE    " -ForegroundColor Magenta  
Write-Host "===============================================" -ForegroundColor Magenta
Write-Host ""

if ($global:DownloadResults) {
    $downloadStats = @($global:DownloadResults.ToArray())
    $downloadSuccess = ($downloadStats | Where-Object { $_.Status -eq "Success" }).Count
    $downloadFailed = ($downloadStats | Where-Object { $_.Status -eq "Failed" }).Count
    Write-Host "📥 DOWNLOAD SUMMARY: $downloadSuccess succeeded, $downloadFailed failed" -ForegroundColor Cyan
}

if ($global:UploadResults) {
    $uploadStats = @($global:UploadResults.ToArray())
    $uploadSuccess = ($uploadStats | Where-Object { $_.Status -eq "Success" }).Count
    $uploadFailed = ($uploadStats | Where-Object { $_.Status -eq "Failed" }).Count
    Write-Host "📤 UPLOAD SUMMARY: $uploadSuccess succeeded, $uploadFailed failed" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "📊 Check the generated HTML reports in: $reportsDir" -ForegroundColor Yellow
Write-Host "📋 Check error files (if any) in: $errorDir" -ForegroundColor Yellow
Write-Host ""

# Final exit
exit 0
