"""Dataset and Case classes for evaluation."""

from dataclasses import dataclass, field


@dataclass
class Case[InputsT, OutputT, MetadataT]:
    """A single test case for evaluation.

    Attributes:
        name: Unique identifier for this case.
        inputs: The input data to pass to the task.
        expected_output: Optional expected output for comparison.
        metadata: Optional metadata for the case (e.g., tags, categories).

    """

    name: str
    inputs: InputsT
    expected_output: OutputT | None = None
    metadata: MetadataT | None = None


@dataclass
class Dataset[InputsT, OutputT, MetadataT]:
    """A collection of test cases.

    Attributes:
        name: Name of the dataset.
        cases: List of test cases.

    """

    cases: list[Case[InputsT, OutputT, MetadataT]] = field(
        default_factory=lambda: []  # noqa: PIE807
    )
    name: str = "evaluation"

    def add_case(
        self,
        name: str,
        inputs: InputsT,
        expected_output: OutputT | None = None,
        metadata: MetadataT | None = None,
    ) -> None:
        """Add a case to the dataset."""
        self.cases.append(
            Case(name=name, inputs=inputs, expected_output=expected_output, metadata=metadata)
        )

    @classmethod
    def from_cases(
        cls, cases: list[Case[InputsT, OutputT, MetadataT]], name: str = "evaluation"
    ) -> Dataset[InputsT, OutputT, MetadataT]:
        """Create a dataset from a list of cases."""
        return cls(cases=cases, name=name)
