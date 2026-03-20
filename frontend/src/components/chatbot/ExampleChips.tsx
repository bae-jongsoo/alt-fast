interface ExampleChipsProps {
  questions: string[];
  onSelect: (question: string) => void;
}

export default function ExampleChips({
  questions,
  onSelect,
}: ExampleChipsProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
      <div className="text-muted-foreground text-center">
        <p className="text-sm font-medium">무엇을 도와드릴까요?</p>
        <p className="mt-1 text-xs">아래 예시를 클릭하거나 직접 질문해보세요</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {questions.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="border-input bg-background hover:bg-accent hover:text-accent-foreground rounded-full border px-4 py-2 text-sm transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
