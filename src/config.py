"""Конфигурация порогов и коэффициентов (без магических чисел в коде)."""

# Часть 2: прогноз
RECENT_WEEKS_FOR_AVG: int = 4
"""Число последних недель для расчёта среднего (улавливает тренд/сдвиг уровня)."""

MIN_WEEKS_FOR_CONFIDENCE: int = 8
"""Минимальная длина истории для высокой уверенности."""

CONFIDENCE_BASE: float = 0.92
"""Базовая уверенность при идеальных данных."""

CONFIDENCE_CV_PENALTY: float = 0.6
"""Штраф за волатильность: confidence -= CV * PENALTY."""

CONFIDENCE_MISSING_PENALTY: float = 0.5
"""Штраф за долю пропусков: confidence -= missing_ratio * PENALTY."""

CONFIDENCE_SHORT_HISTORY_PENALTY: float = 0.15
"""Штраф за короткую историю (< MIN_WEEKS_FOR_CONFIDENCE)."""

CONFIDENCE_OUTLIER_PENALTY: float = 0.1
"""Штраф если обнаружен сдвиг уровня/выброс (нужна осторожность)."""

CONFIDENCE_MIN: float = 0.2
"""Нижняя граница confidence."""

NEEDS_CLARIFICATION_THRESHOLD: float = 0.6
"""Ниже этого порога результат помечается как 'требуется уточнение'."""

OUTLIER_JUMP_RATIO: float = 2.0
"""Во сколько раз медиана последних 4 недель должна превышать медиану первых 8 недель, чтобы считать это сдвигом уровня."""

# Часть 3: разбор вопроса
INTENT_GAP_THRESHOLD: float = 0.15
"""Минимальный разрыв между top1 и top2 скорами интента, иначе unknown."""

INTENT_MIN_SCORE: float = 0.3
"""Минимальный скор top1, иначе unknown."""
