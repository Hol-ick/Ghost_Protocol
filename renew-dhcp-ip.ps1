#requires -Version 5.1
<#
.SYNOPSIS
    Releases and renews the DHCP lease for one active physical network adapter.

.DESCRIPTION
    This script renews the local IPv4 address assigned by a DHCP server. It does
    not guarantee that an ISP will assign a different public IP address.

    When several connected DHCP adapters are found, -InterfaceAlias is required
    so that a VPN, Ethernet, or Wi-Fi connection is not chosen accidentally.

.EXAMPLE
    .\renew-dhcp-ip.ps1

.EXAMPLE
    .\renew-dhcp-ip.ps1 -InterfaceAlias 'Wi-Fi' -ShowPublicIp

.EXAMPLE
    .\renew-dhcp-ip.ps1 -InterfaceAlias 'Ethernet' -WhatIf
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$InterfaceAlias,

    [Parameter()]
    [ValidateRange(0, 60)]
    [int]$WaitSeconds = 3,

    [Parameter()]
    [switch]$SkipRelease,

    [Parameter()]
    [switch]$ShowPublicIp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-Administrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)

    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-DhcpAdapter {
    param(
        [string]$RequestedAlias
    )

    $connectedPhysicalAdapters = Get-NetAdapter -Physical |
        Where-Object { $_.Status -eq 'Up' }

    $dhcpConfigurations = Get-CimInstance -ClassName Win32_NetworkAdapterConfiguration |
        Where-Object { $_.IPEnabled -and $_.DHCPEnabled }

    $eligibleAdapters = @(
        foreach ($adapter in $connectedPhysicalAdapters) {
            $dhcpConfiguration = $dhcpConfigurations |
                Where-Object { $_.InterfaceIndex -eq $adapter.ifIndex } |
                Select-Object -First 1

            if ($null -ne $dhcpConfiguration) {
                $adapter
            }
        }
    )

    if ($RequestedAlias) {
        $requestedAdapter = $eligibleAdapters |
            Where-Object { $_.Name -eq $RequestedAlias } |
            Select-Object -First 1

        if ($null -eq $requestedAdapter) {
            throw "활성 상태이며 DHCP가 설정된 '$RequestedAlias' 어댑터를 찾지 못했습니다. Get-NetAdapter로 이름을 확인하세요."
        }

        return $requestedAdapter
    }

    if ($eligibleAdapters.Count -eq 0) {
        throw '활성 상태이며 DHCP가 설정된 물리 네트워크 어댑터를 찾지 못했습니다.'
    }

    if ($eligibleAdapters.Count -gt 1) {
        $adapterNames = $eligibleAdapters.Name -join "', '"
        throw "여러 DHCP 어댑터가 활성 상태입니다: '$adapterNames'. -InterfaceAlias로 갱신할 어댑터를 지정하세요."
    }

    return $eligibleAdapters[0]
}

function Get-Ipv4Address {
    param(
        [Parameter(Mandatory)]
        [int]$InterfaceIndex
    )

    $address = Get-NetIPAddress -InterfaceIndex $InterfaceIndex -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1

    if ($null -eq $address) {
        return $null
    }

    return $address.IPAddress
}

function Get-PublicIpAddress {
    try {
        return (Invoke-RestMethod -Uri 'https://api.ipify.org?format=json' -TimeoutSec 10).ip
    }
    catch {
        Write-Warning "공인 IP 확인에 실패했습니다: $($_.Exception.Message)"
        return $null
    }
}

function Invoke-IpConfig {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    $ipConfigPath = Join-Path $env:SystemRoot 'System32\ipconfig.exe'
    $output = & $ipConfigPath @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if ($output) {
        Write-Verbose ($output | Out-String)
    }

    if ($exitCode -ne 0) {
        throw "ipconfig $($Arguments -join ' ') 실행이 종료 코드 $exitCode(으)로 실패했습니다."
    }
}

if (-not (Test-Administrator)) {
    throw '이 스크립트는 관리자 권한 PowerShell에서 실행해야 합니다.'
}

$adapter = Get-DhcpAdapter -RequestedAlias $InterfaceAlias
$previousLocalIp = Get-Ipv4Address -InterfaceIndex $adapter.ifIndex
$previousPublicIp = if ($ShowPublicIp) { Get-PublicIpAddress } else { $null }
$previousLocalIpDisplay = if ($previousLocalIp) { $previousLocalIp } else { '없음' }
$previousPublicIpDisplay = if ($previousPublicIp) { $previousPublicIp } else { '확인 실패' }

Write-Host "대상 어댑터: $($adapter.Name)"
Write-Host "현재 로컬 IPv4: $previousLocalIpDisplay"

if ($ShowPublicIp) {
    Write-Host "현재 공인 IP: $previousPublicIpDisplay"
}

if (-not $PSCmdlet.ShouldProcess($adapter.Name, 'DHCP 임대 해제 및 갱신')) {
    return
}

if (-not $SkipRelease) {
    Invoke-IpConfig -Arguments @('/release', $adapter.Name)
}

if ($WaitSeconds -gt 0) {
    Start-Sleep -Seconds $WaitSeconds
}

Invoke-IpConfig -Arguments @('/renew', $adapter.Name)

$currentLocalIp = Get-Ipv4Address -InterfaceIndex $adapter.ifIndex
if ($null -eq $currentLocalIp) {
    throw 'DHCP 갱신 후 유효한 로컬 IPv4 주소를 확인하지 못했습니다.'
}

Write-Host "갱신된 로컬 IPv4: $currentLocalIp"

if ($previousLocalIp -eq $currentLocalIp) {
    Write-Host '로컬 IPv4 주소는 유지되었습니다. DHCP 갱신 자체는 완료되었습니다.'
}
else {
    Write-Host '로컬 IPv4 주소가 변경되었습니다.'
}

if ($ShowPublicIp) {
    $currentPublicIp = Get-PublicIpAddress
    $currentPublicIpDisplay = if ($currentPublicIp) { $currentPublicIp } else { '확인 실패' }
    Write-Host "갱신 후 공인 IP: $currentPublicIpDisplay"

    if ($previousPublicIp -and $currentPublicIp -and $previousPublicIp -eq $currentPublicIp) {
        Write-Warning '공인 IP는 변경되지 않았습니다. 이는 통신사 또는 공유기의 DHCP 임대 정책에 따른 정상적인 결과일 수 있습니다.'
    }
}
