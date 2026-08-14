Set-StrictMode -Version Latest

function Get-HonghuOptionalPropertyText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ''
    }
    return [string]$property.Value
}

function Get-HonghuScheduledTaskActionInspection {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Action)

    $executeProperty = $Action.PSObject.Properties['Execute']
    $execute = Get-HonghuOptionalPropertyText -InputObject $Action -Name 'Execute'
    $arguments = Get-HonghuOptionalPropertyText -InputObject $Action -Name 'Arguments'
    $actionId = Get-HonghuOptionalPropertyText -InputObject $Action -Name 'Id'
    $classId = Get-HonghuOptionalPropertyText -InputObject $Action -Name 'ClassId'

    return [pscustomobject][ordered]@{
        has_execute_property = ($null -ne $executeProperty)
        execute = $execute
        arguments = $arguments
        action_id = $actionId
        class_id = $classId
        searchable_text = (($execute + ' ' + $arguments).Trim()).ToLowerInvariant()
    }
}
