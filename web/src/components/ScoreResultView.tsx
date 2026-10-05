// 评分结果视图 — 分数弹出 + 词级/音素级明细（GOP 的核心价值）。
import type { ScoreResult } from "../lib/api";

export function scoreTier(score: number): { color: string; label: string } {
  if (score >= 80) return { color: "text-leaf", label: "太棒了！" };
  if (score >= 60) return { color: "text-mango-dk", label: "不错哦" };
  return { color: "text-clay", label: "再试一次" };
}

function phonemeCls(score: number): string {
  if (score >= 80) return "bg-leaf-soft text-leaf";
  if (score >= 60) return "bg-desk text-mango-dk";
  return "bg-clay-soft text-clay";
}

export default function ScoreResultView({ result }: { result: ScoreResult }) {
  const score = result.accuracy_score;
  const t = scoreTier(score);
  const words = result.details?.words ?? [];

  return (
    <div className="animate-pop flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <span className={`text-score font-extrabold tabular-nums ${t.color}`}>{score}</span>
        <div className="min-w-0">
          <p className="text-title font-bold">{t.label}</p>
          <p className="text-body text-ink-soft">{result.feedback}</p>
        </div>
      </div>

      {words.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {words.map((w, i) => (
            <div
              key={i}
              className="bg-card border border-desk-line rounded-lg px-3 py-2 max-w-full"
            >
              <div className="flex items-baseline gap-2">
                <span className="text-ui font-bold break-all">{w.word}</span>
                <span className={`text-body font-bold tabular-nums ${scoreTier(w.score).color}`}>
                  {w.score}
                </span>
              </div>
              {w.phonemes && w.phonemes.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {w.phonemes.map((p, j) => (
                    <span
                      key={j}
                      className={`text-[11px] font-bold px-1.5 py-0.5 rounded tabular-nums ${phonemeCls(p.score)}`}
                    >
                      {p.phoneme}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {result.details?.recognized && (
        <p className="text-body text-ink-soft">
          听到的读音：<span className="text-ink font-semibold">{result.details.recognized}</span>
        </p>
      )}
    </div>
  );
}
