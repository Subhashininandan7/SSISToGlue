$ErrorActionPreference = 'Continue'
Write-Host '=== .NET ==='
dotnet --version
Write-Host '=== Python ==='
python --version
Write-Host '=== AWS CLI ==='
aws --version
Write-Host '=== AWS identity ==='
aws sts get-caller-identity --profile ssis-glue-poc
Write-Host '=== AWS profile region ==='
aws configure get region --profile ssis-glue-poc
Write-Host '=== Optional SCT Batch ==='
Get-ChildItem 'C:\Program Files\AWS Schema Conversion Tool' -Filter 'RunSCTBatch.cmd' -Recurse -ErrorAction SilentlyContinue | Select-Object FullName
