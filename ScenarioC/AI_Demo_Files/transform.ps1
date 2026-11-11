$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root 'Employees.csv'
$dst = Join-Path $root 'ActiveEmployees.csv'
$rows = Import-Csv -LiteralPath $src | Where-Object { $_.Status -eq 'Active' } | ForEach-Object {
  $salary = [decimal]::Parse($_.Salary, [System.Globalization.CultureInfo]::InvariantCulture)
  [pscustomobject][ordered]@{
    EmployeeID = $_.EmployeeID
    EmployeeName = $_.EmployeeName
    Department = $_.Department
    Salary = $_.Salary
    Status = $_.Status
    Bonus = ($salary * [decimal]0.10).ToString('F2', [System.Globalization.CultureInfo]::InvariantCulture)
  }
}
$rows | Export-Csv -LiteralPath $dst -NoTypeInformation -Encoding UTF8
Write-Host "Output: $dst"
