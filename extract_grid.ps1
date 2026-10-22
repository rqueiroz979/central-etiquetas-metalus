param(
  [string]$OdsXmlPath = "d:\Documents\ETIQUETA\ods_unzipped\content.xml",
  [int]$RowLimit = 60,
  [int]$ColLimit = 20,
  [string]$OutCsv = "d:\Documents\ETIQUETA\etiqueta_grid.csv",
  [string]$OutYellow = "d:\Documents\ETIQUETA\yellow_cells.csv"
)

$xmlText = Get-Content -Raw -Path $OdsXmlPath
[xml]$doc = $xmlText

$ns = New-Object System.Xml.XmlNamespaceManager($doc.NameTable)
$ns.AddNamespace("table", "urn:oasis:names:tc:opendocument:xmlns:table:1.0")
$ns.AddNamespace("text", "urn:oasis:names:tc:opendocument:xmlns:text:1.0")
$ns.AddNamespace("style", "urn:oasis:names:tc:opendocument:xmlns:style:1.0")
$ns.AddNamespace("fo", "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0")

function Get-CellText([System.Xml.XmlNode]$cell, $nsMgr) {
  $texts = $cell.SelectNodes(".//text:p//text()", $nsMgr)
  $val = ""
  foreach ($t in $texts) { $val += $t.Value }
  return ($val -replace "\s+", " ").Trim()
}

# Collect yellow styles (background #fff2cc)
$yellowStyles = New-Object System.Collections.Generic.HashSet[string]
$styleNodes = $doc.SelectNodes("//style:style[@style:family='table-cell']", $ns)
foreach ($styleNode in $styleNodes) {
  $styleName = $styleNode.Attributes["style:name"].Value
  $cellProps = $styleNode.SelectSingleNode(".//style:table-cell-properties", $ns)
  if ($cellProps -ne $null) {
    $bg = $cellProps.Attributes["fo:background-color"]
    if ($bg -ne $null -and $bg.Value -eq "#fff2cc") {
      [void]$yellowStyles.Add($styleName)
    }
  }
}

$tableNode = $doc.SelectSingleNode("//table:table[@table:name='Etiqueta']", $ns)
if ($tableNode -eq $null) { throw "Tabela 'Etiqueta' nao encontrada." }

$rows = $tableNode.SelectNodes("./table:table-row", $ns)
$grid = @()
$styleGrid = @()

$rowIndex = 0
foreach ($row in $rows) {
  $rowRepeatAttr = $row.Attributes["table:number-rows-repeated"]
  $rowRepeat = if ($rowRepeatAttr) { [int]$rowRepeatAttr.Value } else { 1 }

  for ($rr = 0; $rr -lt $rowRepeat; $rr++) {
    $rowIndex++
    if ($rowIndex -gt $RowLimit) { break }

    $cells = @()
    $styles = @()
    $cellNodes = $row.SelectNodes("./table:table-cell", $ns)
    foreach ($cell in $cellNodes) {
      $colRepeatAttr = $cell.Attributes["table:number-columns-repeated"]
      $colRepeat = if ($colRepeatAttr) { [int]$colRepeatAttr.Value } else { 1 }
      $text = Get-CellText $cell $ns
      $styleNameAttr = $cell.Attributes["table:style-name"]
      $styleName = if ($styleNameAttr) { $styleNameAttr.Value } else { "" }
      for ($cc = 0; $cc -lt $colRepeat; $cc++) {
        if ($cells.Count -lt $ColLimit) {
          $cells += $text
          $styles += $styleName
        }
      }
    }

    # Pad to col limit
    while ($cells.Count -lt $ColLimit) { $cells += "" ; $styles += "" }
    $grid += ,$cells[0..($ColLimit-1)]
    $styleGrid += ,$styles[0..($ColLimit-1)]
  }
  if ($rowIndex -ge $RowLimit) { break }
}

# Write grid CSV
$lines = @()
foreach ($row in $grid) {
  $escaped = $row | ForEach-Object { '"' + ($_ -replace '"','""') + '"' }
  $lines += ($escaped -join ",")
}
$lines | Set-Content -Path $OutCsv -Encoding UTF8

# Write yellow cells CSV: row,col,text,style
$ylines = @("row,col,text,style")
for ($r = 0; $r -lt $styleGrid.Count; $r++) {
  for ($c = 0; $c -lt $styleGrid[$r].Count; $c++) {
    $styleName = $styleGrid[$r][$c]
    if ($styleName -and $yellowStyles.Contains($styleName)) {
      $text = $grid[$r][$c]
      $safeText = ($text -replace '"','""')
      $ylines += ('{0},{1},"{2}",{3}' -f ($r+1), ($c+1), $safeText, $styleName)
    }
  }
}
$ylines | Set-Content -Path $OutYellow -Encoding UTF8

Write-Output "Wrote $OutCsv"
Write-Output "Wrote $OutYellow"
