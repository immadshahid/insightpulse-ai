import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/data/models.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

void main() {
  testWidgets('signed-out users see login, and signing in opens Home', (tester) async {
    final api = defaultApi();
    when(() => api.login(any(), any()))
        .thenAnswer((_) async => AuthResult(token: 'tok', email: 'ayesha.khan@example.com'));
    await pumpApp(tester, api, loggedIn: false);

    expect(find.text('Welcome back'), findsOneWidget);
    await tester.tap(find.text('Sign in'));
    await settle(tester);
    expect(find.text('Enter your email'), findsOneWidget); // validation

    await tester.enterText(find.byType(TextFormField).at(0), 'ayesha.khan@example.com');
    await tester.enterText(find.byType(TextFormField).at(1), 'secret-pass');
    await tester.tap(find.text('Sign in'));
    await settle(tester);

    verify(() => api.login('ayesha.khan@example.com', 'secret-pass')).called(1);
    expect(find.text('Ayesha'), findsOneWidget);
  });

  testWidgets('login shows the server error message', (tester) async {
    final api = defaultApi();
    when(() => api.login(any(), any())).thenThrow(ApiException('Incorrect email or password.', status: 401));
    await pumpApp(tester, api, loggedIn: false);
    await tester.enterText(find.byType(TextFormField).at(0), 'a@example.com');
    await tester.enterText(find.byType(TextFormField).at(1), 'wrong');
    await tester.tap(find.text('Sign in'));
    await settle(tester);
    expect(find.text('Incorrect email or password.'), findsOneWidget);
  });

  testWidgets('Home shows summary, 4 KPIs with changes, chart and actions', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api);

    expect(find.text('Summary'), findsOneWidget);
    expect(find.textContaining('Revenue was PKR 10.6M'), findsOneWidget);
    for (final label in ['Revenue', 'Orders', 'Avg order value', 'Active customers']) {
      expect(find.text(label), findsWidgets);
    }
    expect(find.text('PKR 10.6M'), findsOneWidget);
    expect(find.text('3.9%'), findsOneWidget);
    expect(find.text('No earlier data'), findsOneWidget);
    expect(find.byIcon(Icons.arrow_downward_rounded), findsOneWidget);

    await tester.scrollUntilVisible(find.text('Win back quiet customers'), 300);
    expect(find.textContaining('Within ±9%'), findsOneWidget);
    expect(find.text('High impact'), findsOneWidget);
  });

  testWidgets('changing the period refetches the dashboard', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api);
    await tester.tap(find.text('90D'));
    await settle(tester);
    verify(() => api.dashboard('ds1', '90d')).called(1);
  });

  testWidgets('no data shows the upload empty state', (tester) async {
    final api = defaultApi();
    when(() => api.datasets()).thenAnswer((_) async => []);
    await pumpApp(tester, api);
    expect(find.text('Add your data'), findsOneWidget);
    await tester.tap(find.text('Upload data'));
    await settle(tester);
    expect(find.text('Upload a file'), findsOneWidget);
  });

  testWidgets('dashboard errors offer a retry', (tester) async {
    final api = defaultApi();
    when(() => api.dashboard(any(), any())).thenThrow(ApiException("Can't reach the server."));
    await pumpApp(tester, api);
    expect(find.text('Something went wrong'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('Insights: anomaly card is orange and filters call the API', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api);
    await tester.tap(find.text('Insights').last);
    await settle(tester);

    expect(find.text('Headline for anomalies'), findsOneWidget);
    expect(find.text('2 findings'), findsOneWidget);
    expect(find.text('1 to check'), findsOneWidget);
    expect(find.byIcon(Icons.warning_amber_rounded), findsNWidgets(2)); // card tag + summary
    expect(find.text('Why it matters'), findsWidgets);

    final chip = find.widgetWithText(ChoiceChip, 'Customers');
    await tester.ensureVisible(chip);
    await settle(tester);
    await tester.tap(chip);
    await settle(tester);
    verify(() => api.insights('ds1', category: 'customers')).called(1);
  });

  testWidgets('Forecast shows the total, range, accuracy and what-if', (tester) async {
    final api = defaultApi();
    when(() => api.startForecast(any(), any(), any())).thenAnswer(
      (_) async => Job(
        id: 'j1',
        status: 'succeeded',
        result: {
          'target': 'revenue',
          'target_label': 'Revenue',
          'horizon_days': 90,
          'model': 'prophet',
          'total': 38.1e6,
          'total_lower': 35.3e6,
          'total_upper': 40.9e6,
          'accuracy_note': 'Within ±9% on the last 4 months',
          'change_pct': 22.7,
          'chart_url': '/api/v1/charts/f.png',
          'currency': 'PKR',
        },
      ),
    );
    when(() => api.whatIf(any(), any())).thenAnswer(
      (_) async => WhatIfResult(
        changePct: 10,
        unitsChangePct: -9.6,
        revenueChangePct: 0.1,
        baselineRevenue: 1,
        scenarioRevenue: 1,
        notes: ['Assumes the same number of orders.'],
      ),
    );
    await pumpApp(tester, api);
    await tester.tap(find.text('Forecast').last);
    await settle(tester);

    expect(find.text('PKR 38.1M'), findsOneWidget);
    expect(find.text('Low PKR 35.3M'), findsOneWidget);
    expect(find.text('High PKR 40.9M'), findsOneWidget);
    expect(find.bySemanticsLabel('Likely between PKR 35.3M and PKR 40.9M'), findsOneWidget);
    expect(find.text('22.7%'), findsOneWidget);
    expect(find.text('Best model on your data: Prophet'), findsOneWidget);

    final plus10 = find.descendant(of: find.byType(SegmentedButton<int>), matching: find.text('+10%'));
    await tester.scrollUntilVisible(plus10, 300);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -200));
    await settle(tester);
    await tester.tap(plus10);
    await settle(tester);
    verify(() => api.whatIf('ds1', 10)).called(1);
    expect(find.text('Monthly revenue: PKR 1 \u2192 PKR 1'), findsOneWidget);
    expect(find.text('-9.6%'), findsOneWidget);
    expect(find.text('Assumes the same number of orders.'), findsOneWidget);
  });

  testWidgets('Ask AI: question, answer with chart, how-I-got-this and follow-ups', (tester) async {
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenAnswer(
      (_) async => ChatReply(
        answer: 'Lawn Suit 3pc sold the most: PKR 1.8M.',
        followUps: ['Which city grew fastest?'],
        answerable: true,
        chartUrl: '/api/v1/charts/c.png',
        how: 'Summed revenue by product for 1 Oct 2026 - 31 Oct 2026.',
      ),
    );
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);

    await tester.tap(find.text('Which products sold the most last month?'));
    await settle(tester);
    expect(find.text('Lawn Suit 3pc sold the most: PKR 1.8M.'), findsOneWidget);
    expect(find.text('How I got this'), findsOneWidget);
    expect(find.widgetWithText(ActionChip, 'Which city grew fastest?'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'And last week?');
    await tester.pump(); // the Send button enables once there is text
    await tester.tap(find.byTooltip('Send'));
    await settle(tester);
    final history = verify(() => api.chat('ds1', 'And last week?', captureAny())).captured.single as List;
    expect(history, hasLength(2)); // the first question and its answer
  });

  testWidgets('Ask AI explains when the server has no AI key', (tester) async {
    final api = defaultApi();
    when(() => api.chat(any(), any(), any())).thenThrow(unavailable());
    await pumpApp(tester, api);
    await tester.tap(find.text('Ask AI').last);
    await settle(tester);
    await tester.enterText(find.byType(TextField), 'Top products?');
    await tester.pump();
    await tester.tap(find.byTooltip('Send'));
    await settle(tester);
    expect(find.textContaining('ANTHROPIC_API_KEY'), findsOneWidget);
  });

  testWidgets('Data: AI-mapped columns, role editing and quality score', (tester) async {
    final api = defaultApi();
    when(() => api.saveMapping(any(), any())).thenAnswer((_) async => DatasetProfile.fromJson(profileJson));
    await pumpApp(tester, api);
    await tester.tap(find.text('Data').last);
    await settle(tester);

    await tester.scrollUntilVisible(find.text('AI mapped your columns'), 300);
    expect(find.text('Order Date'), findsOneWidget);
    expect(find.text('City / region'), findsOneWidget);

    await Scrollable.ensureVisible(tester.element(find.text('City / region')), alignment: 0.4);
    await settle(tester, frames: 3);
    await tester.tap(find.text('City / region'));
    await settle(tester);
    await tester.tap(find.text('Not used').last);
    await settle(tester);
    expect(find.text('Your columns'), findsOneWidget); // edited, no longer "AI mapped"

    await tester.scrollUntilVisible(find.text('Save and build my dashboard'), 300);
    await tester.tap(find.text('Save and build my dashboard'));
    await settle(tester);
    final saved = verify(() => api.saveMapping('ds1', captureAny())).captured.single as Map;
    expect(saved['region'], isNull);
    expect(saved['date'], 'Order Date');
  });

  testWidgets('quality card and dark mode toggle', (tester) async {
    final api = defaultApi();
    await pumpApp(tester, api);
    await tester.tap(find.byTooltip('Dark mode'));
    await settle(tester);
    final context = tester.element(find.text('Ayesha'));
    expect(Theme.of(context).brightness, Brightness.dark);

    await tester.tap(find.text('Data').last);
    await settle(tester);
    await tester.scrollUntilVisible(find.text('Excellent'), 300);
    expect(find.text('98'), findsOneWidget);
    expect(find.text('40 rows were exact duplicates and were removed.'), findsOneWidget);
  });
}
