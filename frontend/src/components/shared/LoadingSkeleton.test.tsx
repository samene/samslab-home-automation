import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CardGridSkeleton, TableSkeleton } from "./LoadingSkeleton";

describe("TableSkeleton", () => {
  it("renders the requested number of rows and columns", () => {
    const { container } = render(<TableSkeleton rows={3} columns={4} />);
    const rows = container.querySelectorAll(":scope > div > div");
    expect(rows).toHaveLength(3);
    expect(rows[0].children).toHaveLength(4);
  });
});

describe("CardGridSkeleton", () => {
  it("renders the requested number of card placeholders", () => {
    const { container } = render(<CardGridSkeleton count={5} />);
    expect(container.firstElementChild?.children).toHaveLength(5);
  });
});
