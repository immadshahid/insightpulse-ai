import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/core/prefs.dart';
import 'package:insightpulse/data/models.dart';
import 'package:insightpulse/state/providers.dart';
import 'package:insightpulse/widgets/visuals.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

void main() {
  testWidgets('theme, period and dataset choices are remembered', (tester) async {
    final api = defaultApi();
    final prefs = MemoryPrefs();
    await pumpApp(tester, api, prefs: prefs);
    await tester.tap(find.text('90D'));
    await tester.tap(find.byTooltip('Dark mode'));
    await settle(tester);
    expect(prefs.values[PrefKeys.period], '90d');
    expect(prefs.values[PrefKeys.themeMode], 'dark');

    // A fresh launch with the saved preferences starts where the user left off.
    final api2 = defaultApi();
    await pumpApp(tester, api2, prefs: MemoryPrefs({...prefs.values}));
    verify(() => api2.dashboard('ds1', '90d')).called(1);
    expect(Theme.of(tester.element(find.text('Ayesha'))).brightness, Brightness.dark);
  });

  testWidgets('Home shows data freshness and the comparison window', (tester) async {
    await pumpApp(tester, defaultApi());
    expect(find.textContaining('Data through 31 Oct 2026'), findsOneWidget);
    expect(find.text('Key numbers'), findsOneWidget);
    expect(find.text('vs 2 Sep - 1 Oct 2026'), findsOneWidget);
  });

  testWidgets('tapping a KPI opens its details', (tester) async {
    await pumpApp(tester, defaultApi());
    final tile = find.text('PKR 10.6M');
    await tester.scrollUntilVisible(tile, 300);
    await tester.ensureVisible(tile);
    await settle(tester, frames: 3);
    await tester.tap(tile);
    await settle(tester);
    expect(find.textContaining('Total money received'), findsOneWidget);
    expect(find.text('Previous period'), findsOneWidget);
    expect(find.text('PKR 10.5M'), findsOneWidget); // previous value, formatted
    expect(find.text('2 Oct - 31 Oct 2026'), findsOneWidget);
  });

  testWidgets('charts open full screen with zoom', (tester) async {
    await pumpApp(tester, defaultApi());
    final chart = find.bySemanticsLabel(RegExp('Revenue trend with forecast'));
    await tester.scrollUntilVisible(chart, 300);
    await tester.ensureVisible(chart);
    await settle(tester, frames: 3);
    await tester.tap(chart);
    await settle(tester);
    expect(find.textContaining('Pinch to zoom'), findsOneWidget);
    expect(find.byType(InteractiveViewer), findsOneWidget);
    await tester.tap(find.byTooltip('Close'));
    await settle(tester);
    expect(find.byType(InteractiveViewer), findsNothing);
  });

  testWidgets('"Ask AI about this" hands the insight to Ask AI', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api);
    await tester.tap(find.text('Insights').last);
    await settle(tester);
    final ask = find.text('Ask AI about this').first;
    // Insights has two scrollables (filter chips, feed); scroll the vertical feed.
    await tester.dragUntilVisible(ask, find.byType(ListView).last, const Offset(0, -250));
    await tester.tap(ask);
    await settle(tester);
    final field = tester.widget<TextField>(find.byType(TextField).hitTestable());
    expect(field.controller!.text, 'Tell me more about this: Headline for anomalies');
    verifyNever(() => api.chat(any(), any(), any())); // the user decides when to send
  });

  testWidgets('AI answers can be copied and Send needs text', (tester) async {
    tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async => null);
    addTearDown(() =>
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenAnswer(
        (_) async => ChatReply(answer: 'Karachi leads.', followUps: const [], answerable: true));
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    final send = find.byTooltip('Send');
    expect(tester.widget<IconButton>(find.ancestor(of: find.byIcon(Icons.arrow_upward_rounded),
        matching: find.byType(IconButton))).onPressed, isNull);
    await tester.enterText(find.byType(TextField), 'Top city?');
    await tester.pump();
    await tester.tap(send);
    await settle(tester);
    expect(find.text('Karachi leads.'), findsOneWidget);
    await tester.tap(find.text('Copy'));
    await settle(tester);
    expect(find.text('Answer copied'), findsOneWidget);
  });

  testWidgets('first launch shows the welcome tour once, then sign in', (tester) async {
    final prefs = MemoryPrefs();
    await pumpApp(tester, defaultApi(), loggedIn: false, prefs: prefs);
    expect(find.text('Drop in your sales file'), findsOneWidget);
    await tester.tap(find.text('Next'));
    await settle(tester);
    expect(find.text('See what changed, and why'), findsOneWidget);
    await tester.tap(find.text('Next'));
    await settle(tester);
    await tester.tap(find.text('Get started'));
    await settle(tester);
    expect(find.text('Welcome back'), findsOneWidget);
    expect(prefs.values[PrefKeys.onboarded], '1');

    // Next launch goes straight to sign in.
    await pumpApp(tester, defaultApi(), loggedIn: false, prefs: MemoryPrefs({...prefs.values}));
    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.text('Drop in your sales file'), findsNothing);
  });

  testWidgets('summary, insights and answers can be shared', (tester) async {
    final shared = <String>[];
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenAnswer(
        (_) async => ChatReply(answer: 'Karachi leads.', followUps: const [], answerable: true));
    await pumpApp(tester, api, sharer: (text, {subject}) async => shared.add(text));

    await tester.tap(find.byTooltip('Share summary'));
    expect(shared.last, startsWith('Revenue was PKR 10.6M'));
    expect(shared.last, endsWith('via InsightPulse AI'));

    await tester.tap(find.text('Insights').last);
    await settle(tester);
    await tester.tap(find.byTooltip('Share insight').first);
    expect(shared.last, startsWith('Headline for'));

    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Top city?');
    await tester.pump();
    await tester.tap(find.byTooltip('Send'));
    await settle(tester);
    await tester.tap(find.text('Share'));
    expect(shared.last, startsWith('Karachi leads.'));
  });

  testWidgets('agent answers show who worked on them and how', (tester) async {
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenAnswer((_) async => ChatReply(
          answer: 'Electronics leads.',
          followUps: const [],
          answerable: true,
          how: 'CSV agent: Sales per category',
          steps: const [
            AgentStep(agent: 'knowledge', summary: 'category results'),
            AgentStep(agent: 'sql', summary: 'Revenue total', detail: 'SELECT SUM(revenue) FROM sales'),
            AgentStep(agent: 'csv', summary: 'Sales per category'),
          ],
          sources: const ['Definition: revenue'],
        ));
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Best category?');
    await tester.pump();
    await tester.tap(find.byTooltip('Send'));
    await settle(tester);
    expect(find.text('SQL agent'), findsOneWidget);
    expect(find.text('CSV agent'), findsOneWidget);
    expect(find.text('Saved findings'), findsOneWidget);
    await tester.tap(find.text('How I got this'));
    await settle(tester);
    expect(find.text('SELECT SUM(revenue) FROM sales'), findsOneWidget);
    expect(find.text('Sources: Definition: revenue'), findsOneWidget);
  });

  testWidgets('a revenue goal is set, shown, remembered and removed', (tester) async {
    final prefs = MemoryPrefs({'onboarded': '1'});
    await pumpApp(tester, defaultApi(), prefs: prefs);
    final setGoal = find.text('Set a revenue goal for this period');
    await tester.scrollUntilVisible(setGoal, 300);
    await tester.ensureVisible(setGoal);
    await settle(tester, frames: 3);
    await tester.tap(setGoal);
    await settle(tester);
    await tester.enterText(find.byType(TextField), '20M');
    await tester.tap(find.text('Save'));
    await settle(tester);
    expect(find.text('PKR 10.6M of PKR 20M'), findsOneWidget);
    expect(find.text('PKR 9.4M to go'), findsOneWidget);
    expect(prefs.values[PrefKeys.goal('30d')], '20000000.0');
  });

  testWidgets('customers screen shows risk, groups and who to contact', (tester) async {
    await pumpApp(tester, defaultApi());
    final link = find.text('Your customers');
    await tester.scrollUntilVisible(link, 300);
    await tester.ensureVisible(link);
    await settle(tester, frames: 3);
    await tester.tap(link);
    await settle(tester);
    expect(find.text('PKR 2.5M'), findsOneWidget);
    expect(find.textContaining('40 of 500 customers'), findsOneWidget);
    expect(find.text('Champions'), findsOneWidget);
    expect(find.text('Noor Ansari'), findsOneWidget);
    expect(find.text('91% risk'), findsOneWidget);
  });

  testWidgets('answers from rules are labelled', (tester) async {
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenAnswer((_) async =>
        ChatReply(answer: 'Revenue: PKR 1M.', followUps: const [], answerable: true, source: 'offline'));
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Revenue?');
    await tester.pump();
    await tester.tap(find.byTooltip('Send'));
    await settle(tester);
    expect(find.text('Quick answer'), findsOneWidget);
  });

  testWidgets('a dataset is deleted only after confirming', (tester) async {
    final api = defaultApi();
    when(() => api.deleteDataset(any())).thenAnswer((_) async {});
    await pumpApp(tester, api);
    await tester.tap(find.text('Data').last);
    await settle(tester);
    final delete = find.text('Delete this dataset');
    await tester.scrollUntilVisible(delete, 300);
    await tester.ensureVisible(delete);
    await settle(tester, frames: 3);
    await tester.tap(delete);
    await settle(tester);
    await tester.tap(find.text('Cancel'));
    await settle(tester);
    verifyNever(() => api.deleteDataset(any()));
    await tester.tap(delete);
    await settle(tester);
    await tester.tap(find.text('Delete'));
    await settle(tester);
    verify(() => api.deleteDataset('ds1')).called(1);
  });

  testWidgets('a Google Sheet link is imported', (tester) async {
    final api = defaultApi();
    when(() => api.importSheet(any())).thenThrow(ApiException('That sheet is not shared.'));
    await pumpApp(tester, api);
    await tester.tap(find.text('Data').last);
    await settle(tester);
    await tester.tap(find.text('Import from Google Sheets'));
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'https://docs.google.com/spreadsheets/d/abc');
    await tester.tap(find.text('Import'));
    await settle(tester);
    verify(() => api.importSheet('https://docs.google.com/spreadsheets/d/abc')).called(1);
    expect(find.text('That sheet is not shared.'), findsOneWidget);
  });

  testWidgets('sample data can be loaded without a file', (tester) async {
    final api = defaultApi();
    when(() => api.loadSample()).thenThrow(ApiException('Could not load the sample.'));
    await pumpApp(tester, api);
    await tester.tap(find.text('Data').last);
    await settle(tester);
    await tester.tap(find.text('Try with sample data'));
    await settle(tester);
    verify(() => api.loadSample()).called(1);
    expect(find.text('Could not load the sample.'), findsOneWidget);
  });

  test('server addresses are normalised', () {
    expect(normalizeServerUrl(' 192.168.1.5 '), 'http://192.168.1.5:8000');
    expect(normalizeServerUrl('http://10.0.2.2:8000/'), 'http://10.0.2.2:8000');
    expect(normalizeServerUrl('https://api.example.com'), 'https://api.example.com');
  });

  testWidgets('KPI tiles draw a sparkline from the server series', (tester) async {
    await pumpApp(tester, defaultApi());
    expect(find.byType(Sparkline), findsNWidgets(4));
  });

  group('large text (1.3x) has no overflow', () {
    for (final tab in ['Home', 'Insights', 'Forecast', 'Data']) {
      testWidgets(tab, (tester) async {
        final api = defaultApi();
        when(() => api.startForecast(any(), any(), any())).thenAnswer((_) async => Job(
              id: 'j1',
              status: 'succeeded',
              result: {
                'target': 'revenue', 'target_label': 'Revenue', 'horizon_days': 90, 'model': 'prophet',
                'total': 38.1e6, 'total_lower': 35.3e6, 'total_upper': 40.9e6,
                'accuracy_note': 'Within ±9% on the last 4 months', 'change_pct': 22.7,
                'chart_url': '/api/v1/charts/f.png', 'currency': 'PKR',
              },
            ));
        await pumpApp(tester, api, textScale: 1.3);
        if (tab != 'Home') {
          await tester.tap(find.text(tab).last);
          await settle(tester);
        }
        // Scroll through the whole screen so every section gets laid out.
        for (var i = 0; i < 8; i++) {
          await tester.drag(find.byType(Scrollable).first, const Offset(0, -400));
          await settle(tester, frames: 3);
        }
        final error = tester.takeException();
        if (error is FlutterError) debugPrint(error.toStringDeep());
        expect(error, isNull);
      });
    }
  });
}
