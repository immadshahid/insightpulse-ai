import 'package:intl/intl.dart';

/// 1234567 -> "1.2M", 45300 -> "45.3K" (matches the backend's formatting).
String compactNumber(num value) {
  final a = value.abs();
  if (a >= 1e9) return '${_trim(value / 1e9)}B';
  if (a >= 1e6) return '${_trim(value / 1e6)}M';
  if (a >= 1e3) return '${_trim(value / 1e3)}K';
  return NumberFormat.decimalPattern().format(value.round());
}

/// 1234567 -> "1,234,567".
String wholeNumber(num value) => NumberFormat.decimalPattern().format(value.round());

String _trim(num v) {
  final s = v.toStringAsFixed(1);
  return s.endsWith('.0') ? s.substring(0, s.length - 2) : s;
}

/// "PKR 1.2M" or "1.2M" when the currency is unknown.
String money(num value, String? currency) =>
    currency == null ? compactNumber(value) : '$currency ${compactNumber(value)}';

/// "+4.1%" / "-2.9%".
String signedPct(num value, {int digits = 1}) =>
    '${value >= 0 ? '+' : '-'}${value.abs().toStringAsFixed(digits)}%';

String greeting(DateTime now) {
  final h = now.hour;
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

final _day = DateFormat('d MMM');
final _dayYear = DateFormat('d MMM y');

/// "2 Oct - 31 Oct 2026" (year shown once when both dates share it).
String dateRange(DateTime start, DateTime end) =>
    start.year == end.year ? '${_day.format(start)} - ${_dayYear.format(end)}'
        : '${_dayYear.format(start)} - ${_dayYear.format(end)}';

/// "31 Oct 2026".
String shortDate(DateTime d) => _dayYear.format(d);

/// "previous 30 days", "previous 12 months".
String previousPeriodLabel(String period) => switch (period) {
      '7d' => 'previous 7 days',
      '90d' => 'previous 90 days',
      '1y' => 'previous 12 months',
      _ => 'previous 30 days',
    };
