from dataclasses import dataclass


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    """Stops a paid run before its projected spend passes max_usd. The projection uses the
    average cost of the paid units so far, so the first unit always runs. Units served
    from cache cost nothing and are not recorded."""

    max_usd: float
    spent: float = 0.0
    done: int = 0

    def record(self, cost_usd: float) -> None:
        self.spent += cost_usd
        self.done += 1

    def projected(self, remaining: int) -> float:
        if self.done == 0:
            return self.spent
        return self.spent + self.spent / self.done * remaining

    def check(self, remaining: int) -> None:
        projected = self.projected(remaining)
        if projected > self.max_usd:
            raise BudgetExceeded(
                f"projected ${projected:.2f} for the remaining {remaining} would pass the "
                f"${self.max_usd:.2f} cap (spent ${self.spent:.2f})"
            )
