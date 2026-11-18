import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:insightpulse/core/api_client.dart';
import 'package:insightpulse/data/models.dart';
import 'package:insightpulse/features/clean_screen.dart';
import 'package:mocktail/mocktail.dart';

import 'support.dart';

const dedupe = {'op': 'remove_duplicates', 'columns': <String>[]};
const dropAge = {
  'op': 'drop_missing',
  'columns': ['Age'],
};

CleanSuggestions suggestions({bool ai = true}) => CleanSuggestions.fromJson({
      'suggestions': [
        {
          'label': 'Remove 3 duplicate rows',
          'steps': [dedupe],
        },
      ],
      'ai_available': ai,
    });

CleanPreview previewOf(List<CleanStep> steps) => CleanPreview.fromJson({
      'rows_before': 43,
      'rows_after': 43 - 3 * steps.length,
      'columns_before': 6,
      'columns_after': 6,
      'steps': [
        for (final s in steps)
          {
            'step': s,
            'description': s['op'] == 'remove_duplicates'
                ? 'Remove rows that are exact copies'
                : 'Remove rows where Age is missing',
            'effect': 'Removes 3 rows',
          },
      ],
    });

MockApi cleanApi({bool ai = true}) {
  final api = defaultApi();
  when(() => api.cleanSuggestions(any())).thenAnswer((_) async => suggestions(ai: ai));
  when(() => api.cleanPreview(any(), any())).thenAnswer(
    (inv) async => previewOf((inv.positionalArguments[1] as List).cast<CleanStep>()),
  );
  return api;
}

Future<void> openClean(WidgetTester tester) async {
  await tester.tap(find.text('Data').last);
  await settle(tester);
  await tester.tap(find.text('Clean this data'));
  await settle(tester);
}

Finder inScreen(Finder f) => find.descendant(of: find.byType(CleanScreen), matching: f);

Future<void> scrollTo(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(target, 200, scrollable: inScreen(find.byType(Scrollable)).first);
  await settle(tester, frames: 3);
}

void main() {
  testWidgets('a suggested fix is previewed, then applied as a new dataset', (tester) async {
    final api = cleanApi();
    when(() => api.cleanApply(any(), any())).thenAnswer(
      (_) async => DatasetProfile.fromJson({
        ...profileJson,
        'dataset': {...datasetJson, 'id': 'clean1', 'name': 'My shop (cleaned)'},
      }),
    );
    await pumpApp(tester, api);
    await openClean(tester);
    expect(find.text('Tell me what to fix'), findsOneWidget);
    final apply = inScreen(find.widgetWithText(FilledButton, 'Create cleaned copy'));
    expect(tester.widget<FilledButton>(apply).onPressed, isNull); // nothing to apply yet

    await tester.tap(find.text('Remove 3 duplicate rows'));
    await settle(tester);
    verify(() => api.cleanPreview('ds1', [dedupe])).called(1);
    expect(find.text('Changes to apply'), findsOneWidget);
    expect(find.text('Remove rows that are exact copies'), findsOneWidget);
    expect(find.text('43 → 40'), findsOneWidget);
    expect(find.text('Remove 3 duplicate rows'), findsNothing); // moved into the plan

    await scrollTo(tester, find.text('Create cleaned copy'));
    await tester.tap(find.text('Create cleaned copy'));
    await settle(tester);
    verify(() => api.cleanApply('ds1', [dedupe])).called(1);
    expect(find.byType(CleanScreen), findsNothing);
  });

  testWidgets('a typed request adds steps, and a step can be removed', (tester) async {
    final api = cleanApi();
    when(() => api.cleanPlan(any(), any()))
        .thenAnswer((_) async => (steps: <CleanStep>[dropAge], note: 'There is no Notes column, so I left that out.'));
    await pumpApp(tester, api);
    await openClean(tester);
    await tester.enterText(inScreen(find.byType(TextField)), 'Remove rows where age is missing');
    await tester.tap(find.byTooltip('Add this change'));
    await settle(tester);
    verify(() => api.cleanPlan('ds1', 'Remove rows where age is missing')).called(1);
    expect(find.text('Remove rows where Age is missing'), findsOneWidget);
    expect(find.text('There is no Notes column, so I left that out.'), findsOneWidget);
    expect(tester.widget<TextField>(inScreen(find.byType(TextField))).controller!.text, isEmpty);

    await scrollTo(tester, find.byTooltip('Remove this change'));
    await tester.tap(find.byTooltip('Remove this change'));
    await settle(tester);
    expect(find.text('Changes to apply'), findsNothing);
  });

  testWidgets('a request that cannot be done shows why and keeps the text', (tester) async {
    final api = cleanApi();
    when(() => api.cleanPlan(any(), any())).thenThrow(ApiException("I can't add calculated columns yet.", status: 422));
    await pumpApp(tester, api);
    await openClean(tester);
    await tester.enterText(inScreen(find.byType(TextField)), 'add a profit column');
    await tester.tap(find.byTooltip('Add this change'));
    await settle(tester);
    expect(find.text("I can't add calculated columns yet."), findsOneWidget);
    expect(find.text('add a profit column'), findsOneWidget);
    expect(find.text('Changes to apply'), findsNothing);
  });

  testWidgets('without AI only the suggested fixes are offered', (tester) async {
    await pumpApp(tester, cleanApi(ai: false));
    await openClean(tester);
    expect(inScreen(find.byType(TextField)), findsNothing);
    expect(find.textContaining('Typed requests need AI'), findsOneWidget);
    expect(find.text('Remove 3 duplicate rows'), findsOneWidget);
  });
}
