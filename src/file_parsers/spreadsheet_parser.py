"""
Spreadsheet Parser for extracting data from Excel and CSV files.

Supports XLSX, XLS, and CSV formats with multi-sheet handling.
Converts data to markdown format with row/column indices for accurate cell references.
"""

import pandas as pd
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SpreadsheetSheet:
    """Represents a single sheet from a spreadsheet."""
    name: str
    data: pd.DataFrame
    
    @property
    def row_count(self) -> int:
        """Number of data rows (excluding header)."""
        return len(self.data)
    
    @property
    def col_count(self) -> int:
        """Number of columns."""
        return len(self.data.columns)
    
    def to_markdown(self, include_indices: bool = True, max_rows: Optional[int] = None) -> str:
        """
        Convert sheet to markdown format with row numbers and column letters.
        
        Args:
            include_indices: Whether to include row numbers and column letters
            max_rows: Maximum rows to include (None for all)
        
        Returns:
            Markdown-formatted table string
        """
        if self.data.empty:
            return f"=== Sheet: {self.name} ===\n[Empty sheet]"
        
        df = self.data
        if max_rows and len(df) > max_rows:
            df = df.head(max_rows)
            truncated = True
        else:
            truncated = False
        
        lines = [f"=== Sheet: {self.name} ==="]
        
        if include_indices:
            # Build table with column letters and row numbers
            # Column letters: A, B, C, ... Z, AA, AB, etc.
            col_letters = self._get_column_letters(len(df.columns))
            
            # Header row with column letters
            header_cells = [""] + col_letters  # Empty cell for row number column
            lines.append("| " + " | ".join(header_cells) + " |")
            
            # Separator
            lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")
            
            # Column names row (row 1)
            col_names = [self._clean_cell(str(col)) for col in df.columns]
            lines.append("| 1 | " + " | ".join(col_names) + " |")
            
            # Data rows (starting from row 2)
            for idx, (_, row) in enumerate(df.iterrows(), start=2):
                cells = [self._clean_cell(str(val)) for val in row.values]
                lines.append(f"| {idx} | " + " | ".join(cells) + " |")
        else:
            # Simple markdown table without indices
            # Header
            col_names = [self._clean_cell(str(col)) for col in df.columns]
            lines.append("| " + " | ".join(col_names) + " |")
            
            # Separator
            lines.append("| " + " | ".join(["---"] * len(col_names)) + " |")
            
            # Data rows
            for _, row in df.iterrows():
                cells = [self._clean_cell(str(val)) for val in row.values]
                lines.append("| " + " | ".join(cells) + " |")
        
        if truncated:
            lines.append(f"[... truncated, showing first {max_rows} of {self.row_count} rows]")
        
        return "\n".join(lines)
    
    def _get_column_letters(self, num_cols: int) -> List[str]:
        """Generate Excel-style column letters (A, B, ..., Z, AA, AB, ...)."""
        letters = []
        for i in range(num_cols):
            result = ""
            n = i
            while True:
                result = chr(65 + (n % 26)) + result
                n = n // 26 - 1
                if n < 0:
                    break
            letters.append(result)
        return letters
    
    def _clean_cell(self, value: str) -> str:
        """Clean cell value for markdown display."""
        if value == "nan" or value == "None":
            return ""
        # Replace pipe characters that would break markdown
        value = value.replace("|", "\\|")
        # Replace newlines with spaces
        value = value.replace("\n", " ").replace("\r", "")
        # Trim excessive whitespace
        value = " ".join(value.split())
        # Truncate very long cells
        if len(value) > 100:
            value = value[:97] + "..."
        return value
    
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int:
        """Estimate token count based on character count."""
        return int(len(self.to_markdown()) / chars_per_token)


@dataclass
class SpreadsheetParseResult:
    """Result of parsing a spreadsheet file."""
    filename: str
    file_type: str  # 'xlsx', 'xls', or 'csv'
    sheets: List[SpreadsheetSheet]
    error: Optional[str] = None
    
    @property
    def sheet_count(self) -> int:
        """Number of sheets."""
        return len(self.sheets)
    
    @property
    def total_rows(self) -> int:
        """Total rows across all sheets."""
        return sum(sheet.row_count for sheet in self.sheets)
    
    def to_markdown(self, include_indices: bool = True, max_rows_per_sheet: Optional[int] = None) -> str:
        """
        Convert all sheets to markdown format.
        
        Args:
            include_indices: Whether to include row numbers and column letters
            max_rows_per_sheet: Maximum rows per sheet (None for all)
        
        Returns:
            Markdown string with all sheets
        """
        if self.error:
            return f"[Error parsing spreadsheet: {self.error}]"
        
        parts = [f"=== Spreadsheet: {self.filename} ({self.sheet_count} sheet{'s' if self.sheet_count != 1 else ''}) ==="]
        
        for sheet in self.sheets:
            parts.append(sheet.to_markdown(include_indices, max_rows_per_sheet))
        
        return "\n\n".join(parts)
    
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int:
        """Estimate token count based on character count."""
        total_chars = len(self.to_markdown())
        return int(total_chars / chars_per_token)


class SpreadsheetParser:
    """Parser for extracting data from spreadsheet files (XLSX, XLS, CSV)."""
    
    DEFAULT_MAX_ROWS = 500  # Per sheet
    
    def __init__(self):
        pass
    
    def parse(
        self,
        file_path: str,
        max_rows_per_sheet: Optional[int] = None
    ) -> SpreadsheetParseResult:
        """
        Parse a spreadsheet file and extract all sheets.
        
        Args:
            file_path: Path to the spreadsheet file
            max_rows_per_sheet: Maximum rows to extract per sheet (None for DEFAULT_MAX_ROWS)
        
        Returns:
            SpreadsheetParseResult with extracted content
        """
        file_path = Path(file_path)
        filename = file_path.name
        suffix = file_path.suffix.lower()
        
        if max_rows_per_sheet is None:
            max_rows_per_sheet = self.DEFAULT_MAX_ROWS
        
        # Determine file type
        if suffix in ['.xlsx', '.xlsm']:
            file_type = 'xlsx'
        elif suffix == '.xls':
            file_type = 'xls'
        elif suffix == '.csv':
            file_type = 'csv'
        else:
            return SpreadsheetParseResult(
                filename=filename,
                file_type='unknown',
                sheets=[],
                error=f"Unsupported file type: {suffix}"
            )
        
        try:
            if file_type == 'csv':
                sheets = self._parse_csv(file_path, max_rows_per_sheet)
            else:
                sheets = self._parse_excel(file_path, max_rows_per_sheet)
            
            return SpreadsheetParseResult(
                filename=filename,
                file_type=file_type,
                sheets=sheets
            )
            
        except Exception as e:
            return SpreadsheetParseResult(
                filename=filename,
                file_type=file_type,
                sheets=[],
                error=str(e)
            )
    
    def _parse_excel(self, file_path: Path, max_rows: int) -> List[SpreadsheetSheet]:
        """Parse Excel file (XLSX or XLS) with all sheets."""
        sheets = []
        
        # Read all sheets
        with pd.ExcelFile(file_path) as excel_file:
            for sheet_name in excel_file.sheet_names:
                try:
                    # Read sheet with limited rows
                    df = pd.read_excel(
                        excel_file,
                        sheet_name=sheet_name,
                        nrows=max_rows
                    )
                    
                    # Skip completely empty sheets
                    if df.empty:
                        continue
                    
                    sheets.append(SpreadsheetSheet(
                        name=sheet_name,
                        data=df
                    ))
                except Exception as e:
                    # If a sheet fails to parse, include it with an error note
                    sheets.append(SpreadsheetSheet(
                        name=sheet_name,
                        data=pd.DataFrame({'Error': [f'Failed to parse: {str(e)}']})
                    ))
        
        return sheets
    
    def _parse_csv(self, file_path: Path, max_rows: int) -> List[SpreadsheetSheet]:
        """Parse CSV file as a single sheet."""
        # Try different encodings
        encodings = ['utf-8', 'latin-1', 'cp1252']
        df = None
        last_error = None
        
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding, nrows=max_rows)
                break
            except Exception as e:
                last_error = e
                continue
        
        if df is None:
            raise last_error or ValueError("Could not parse CSV file")
        
        # Use filename without extension as sheet name
        sheet_name = file_path.stem
        
        return [SpreadsheetSheet(name=sheet_name, data=df)]
    
    def get_sheet_info(self, file_path: str) -> Dict[str, Any]:
        """
        Get basic info about a spreadsheet without fully parsing it.
        
        Returns:
            Dict with 'sheet_count', 'sheet_names', 'file_type'
        """
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        
        if suffix == '.csv':
            return {
                'sheet_count': 1,
                'sheet_names': [file_path.stem],
                'file_type': 'csv'
            }
        
        try:
            with pd.ExcelFile(file_path) as excel_file:
                return {
                    'sheet_count': len(excel_file.sheet_names),
                    'sheet_names': excel_file.sheet_names,
                    'file_type': 'xlsx' if suffix == '.xlsx' else 'xls'
                }
        except Exception as e:
            raise ValueError(f"Could not read spreadsheet: {str(e)}")
