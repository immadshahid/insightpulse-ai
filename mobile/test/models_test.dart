import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/format.dart';
import 'package:insightpulse/data/models.dart';

import 'support.dart';

void main() {
  group('format', () {
    test('compact numbers match the backend', () {
      expect(compactNumber(1234567), '1.2M');
      expect(compactNumber(45300), '45.3K');
      expect(compactNumber(2000000), '2M');
      expect(compactNumber(950), '950');
      expect(money(10.6e6, 'PKR'), 'PKR 10.6M');
      expect(money(500, null), '500');
    });

    test('signed percentages and greeting', () {
      expect(signedPct(4.12), '+4.1%');
      expect(signedPct(-2.9), '-2.9%');
      expect(greeting(DateTime(2026, 1, 1, 9)), 'Good morning');
      expect(greeting(DateTime(2026, 1, 1, 20)), 'Good evening');
    });
  });

  group('models', () {
    test('dashboard parses KPIs, summary and forecast state', () {
      final d = Dashboard.fromJson(dashboardJson(forecast: 'pending'));
      expect(d.kpis, hasLength(4));
      expect(d.kpis.last.changePct, isNull);
      expect(d.trendChartUrl, '/api/v1/charts/trend.png');
      expect(d.isPending, isTrue);
      expect(Dashboard.fromJson(dashboardJson()).isPending, isFalse);
    });

    test('profile builds role <-> column maps', () {
      final p = DatasetProfile.fromJson(profileJson);
      expect(p.mapping['date'], 'Order Date');
      expect(p.mapping['quantity'], isNull);
      expect(p.roleByColumn['City'], 'region');
      expect(p.mappingSource, 'llm');
      expect(p.quality!.score, 98);
    });

    test('forecast result and chat reply', () {
      final f = ForecastResult.fromJson({
        'target': 'revenue', 'target_label': 'Revenue', 'horizon_days': 90, 'model': 'prophet',
        'total': 38.1e6, 'total_lower': 35.3e6, 'total_upper': 40.9e6,
        'accuracy_note': 'Within ±9% on the last 4 months', 'change_pct': 22.7, 'chart_url': '/c.png',
        'currency': 'PKR',
      });
      expect(f.total, 38.1e6);
      expect(f.changePct, 22.7);
      final c = ChatReply.fromJson({'answer': 'Hi', 'follow_ups': ['a', 'b'], 'answerable': false});
      expect(c.followUps, ['a', 'b']);
      expect(c.answerable, isFalse);
      expect(c.chartUrl, isNull);
    });
  });
}
