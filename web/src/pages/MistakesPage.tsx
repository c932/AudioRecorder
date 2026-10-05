import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type WordItem } from "../lib/api";
import { PageHeader, Spinner, ErrorText, btnPrimary } from "../components/ui";
import { SpeakerIcon } from "../components/icons";
import { speak } from "../lib/audio";

/** 错题本 — 发音低分词 + 翻译错词，一键拿去跟读。 */
export default function MistakesPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"oral" | "quiz">("oral");
  const [oral, setOral] = useState<WordItem[] | null>(null);
  const [quiz, setQuiz] = useState<WordItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .mistakes()
      .then((r) => {
        setOral(r.oral);
        setQuiz(r.quiz);
      })
      .catch((e) => setError(e.message));
  }, []);

  const items = tab === "oral" ? oral : quiz;
  const practice = () => {
    if (!items?.length) return;
    navigate("/practice", { state: { items } });
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="错题本" />
      <ErrorText text={error} />

      <div className="flex gap-2">
        {(
          [
            ["oral", `发音 ${oral?.length ?? 0}`],
            ["quiz", `翻译 ${quiz?.length ?? 0}`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-4 py-2 rounded-lg text-ui font-bold border transition-colors ${
              tab === key
                ? "bg-mango border-mango-dk text-ink"
                : "bg-card border-desk-line text-ink-soft hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {!items && <Spinner />}
      {items?.length === 0 && (
        <p className="text-ui text-ink-soft text-center py-8">
          {tab === "oral" ? "发音都练得不错，没有错题" : "翻译全对，没有错题"}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {items?.map((w, i) => (
          <div
            key={i}
            className="bg-card border border-desk-line rounded-lg px-3 py-2 flex items-center gap-2"
          >
            <div className="min-w-0 flex-1">
              <p className="text-ui font-bold truncate">{w.text}</p>
              <p className="text-body text-ink-soft truncate">{w.translation}</p>
            </div>
            {tab === "oral" ? (
              <span
                className={`text-ui font-bold tabular-nums shrink-0 ${
                  (w.last_score ?? 0) >= 60 ? "text-mango-dk" : "text-clay"
                }`}
              >
                {w.last_score ?? 0}
              </span>
            ) : (
              <span className="text-ui font-bold text-clay tabular-nums shrink-0">
                ×{w.quiz_wrong}
              </span>
            )}
            <button
              type="button"
              onClick={() => speak(w.text).catch(() => {})}
              aria-label={`朗读 ${w.text}`}
              className="p-2 rounded-lg text-ink-soft hover:bg-desk hover:text-ink shrink-0"
            >
              <SpeakerIcon className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {items && items.length > 0 && (
        <button className={btnPrimary} onClick={practice}>
          跟读这些错题
        </button>
      )}
    </div>
  );
}
