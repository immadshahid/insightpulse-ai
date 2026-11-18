import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/data/models.dart';
import 'package:insightpulse/features/combine_screen.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

final ordersJson = {...datasetJson, 'id': 'orders', 'name': 'Orders', 'row_count': 200};
final customersJson = {...datasetJson, 'id': 'customers', 'name': 'Customers', 'row_count': 18, 'kind': 'general'};

final joinPreviewJson = {
  'suggested': 'join',
  'stack': {'possible': false, 'reason': "These files don't have the same columns, so they can't be stacked."},
  'join': {
    'possible': true,
    'base': 'Orders',
    'rows': 200,
    'columns': 7,
    'steps': [
      {
        'left': 'Orders',
        'right': 'Customers',
        'left_column': 'customer_id',
        'right_column': 'Customer ID',
        'match_pct': 90.0,
        'columns_added': 2,
      },
    ],
  },
};

final noFitJson = {
  'suggested': null,
  'stack': {'possible': false, 'reason': 'Not the same columns.'},
  'join': {'possible': false, 'reason': "Couldn't find a column that links Customers to Orders."},
};

MockApi twoDatasets() {
  final api = defaultApi();
  when(() => api.datasets()).thenAnswer(
    (_) async => [DatasetSummary.fromJson(ordersJson), DatasetSummary.fromJson(customersJson)],
  );
  return api;
}

Future<void> openCombine(WidgetTester tester) async {
  await tester.tap(find.text('Data').last);
  await settle(tester);
  await tester.tap(find.text('Combine datasets'));
  await settle(tester);
}

Finder inScreen(Finder f) => find.descendant(of: find.byType(CombineScreen), matching: f);

Future<void> tick(WidgetTester tester, String name) async {
  await tester.tap(inScreen(find.widgetWithText(CheckboxListTile, name)));
  await settle(tester, frames: 4);
}

void main() {
  testWidgets('the Combine card needs two datasets', (tester) async {
    await pumpApp(tester, defaultApi()); // one dataset
    await tester.tap(find.text('Data').last);
    await settle(tester);
    expect(find.text('Combine datasets'), findsNothing);
  });

  testWidgets('related files are previewed as a join and combined', (tester) async {
    final api = twoDatasets();
    when(() => api.combinePreview(any())).thenAnswer((_) async => CombinePreview.fromJson(joinPreviewJson));
    when(() => api.combine(any(), any(), name: any(named: 'name'))).thenAnswer(
      (_) async => DatasetProfile.fromJson({
        ...profileJson,
        'dataset': {...datasetJson, 'id': 'new', 'name': 'Orders + Customers'},
      }),
    );
    await pumpApp(tester, api);
    await openCombine(tester);
    expect(find.text('Tick at least two datasets to see how they fit together.'), findsOneWidget);

    await tick(tester, 'Orders');
    verifyNever(() => api.combinePreview(any()));
    await tick(tester, 'Customers');
    verify(() => api.combinePreview(['orders', 'customers'])).called(1);
    expect(find.text('Orders with details added from the others'), findsOneWidget);
    expect(find.text('Customers linked by customer_id'), findsOneWidget);
    expect(find.textContaining('90% of rows matched'), findsOneWidget);

    final create = find.text('Combine 2 datasets');
    await tester.scrollUntilVisible(create, 200, scrollable: inScreen(find.byType(Scrollable)).first);
    await tester.tap(create);
    await settle(tester);
    verify(() => api.combine(['orders', 'customers'], 'join', name: null)).called(1);
    expect(find.byType(CombineScreen), findsNothing); // back in the app, on Home
  });

  testWidgets('files that do not fit explain why and cannot be combined', (tester) async {
    final api = twoDatasets();
    when(() => api.combinePreview(any())).thenAnswer((_) async => CombinePreview.fromJson(noFitJson));
    await pumpApp(tester, api);
    await openCombine(tester);
    await tick(tester, 'Orders');
    await tick(tester, 'Customers');
    expect(find.text("These files don't fit together yet"), findsOneWidget);
    expect(find.textContaining("Couldn't find a column"), findsOneWidget);
    final button = tester.widget<FilledButton>(inScreen(find.byType(FilledButton)));
    expect(button.onPressed, isNull);
  });

  testWidgets('a server problem while combining is shown', (tester) async {
    final api = twoDatasets();
    when(() => api.combinePreview(any())).thenAnswer((_) async => CombinePreview.fromJson(joinPreviewJson));
    when(() => api.combine(any(), any(), name: any(named: 'name')))
        .thenThrow(ApiException('The combined file is too large.'));
    await pumpApp(tester, api);
    await openCombine(tester);
    await tick(tester, 'Orders');
    await tick(tester, 'Customers');
    final create = find.text('Combine 2 datasets');
    await tester.scrollUntilVisible(create, 200, scrollable: inScreen(find.byType(Scrollable)).first);
    await tester.tap(create);
    await settle(tester);
    expect(find.text('The combined file is too large.'), findsOneWidget);
    expect(find.byType(CombineScreen), findsOneWidget);
  });
}
