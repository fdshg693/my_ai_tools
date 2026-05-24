# This is a sample script demonstrating how to create a simple Prefab UI app using FastMCP.

from fastmcp import FastMCP

from prefab_ui.components import Column, Heading
from prefab_ui.components.charts import BarChart, ChartSeries
from prefab_ui.app import PrefabApp

mcp = FastMCP("My App Server")


@mcp.tool(app=True)
def revenue_chart(year: int) -> PrefabApp:
    """Show annual revenue as an interactive bar chart."""
    data = [
        {"quarter": "Q1", "revenue": 42000},
        {"quarter": "Q2", "revenue": 51000},
        {"quarter": "Q3", "revenue": 47000},
        {"quarter": "Q4", "revenue": 63000},
    ]

    with Column(gap=4, css_class="p-6") as view:
        Heading(f"{year} Revenue")
        BarChart(
            data=data,
            series=[ChartSeries(data_key="revenue", label="Revenue")],
            x_axis="quarter",
        )

    return PrefabApp(view=view)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
