"""Study/Scan container tests: what a PvDataset exposes to the layers above it."""


def test_data_init(dataset):
    """The Study container builds from each study and lists its scans."""
    for studyobj in dataset.values():
        assert studyobj.avail, 'Study should enumerate available scans'


def test_scan_lists_its_reconstructions(dataset):
    """Every listed scan resolves to a Scan whose reconstructions are numbered."""
    for studyobj in dataset.values():
        for scan_id in studyobj.avail:
            recos = studyobj.get_scan(scan_id).avail
            assert all(isinstance(reco_id, int) for reco_id in recos)


def test_scan_binds_the_requested_reconstruction(dataset):
    """A scan reads the parameters of the reco it was asked for, not its default.

    Regression: a derived reconstruction decoded with the primary reco's word
    type and matrix failed to reshape.
    """
    for studyobj in dataset.values():
        for scan_id in studyobj.avail:
            scanobj = studyobj.get_scan(scan_id)
            if len(scanobj.avail) < 2:
                continue
            for reco_id in scanobj.avail:
                dataset_ = scanobj.get_dataset(reco_id)
                assert int(dataset_.path.parent.name) == reco_id
            return


def test_study_recipe_names_whose_attribute_each_field_is():
    """``SUBJECT_name_string`` is the subject's name -- it was printed as
    'Researcher' -- and ``##OWNER`` (the login) must not overwrite PV360's
    ``SUBJECT_study_operator`` (the operator entered at registration)."""
    from types import SimpleNamespace

    from pvraw.api.data.study import _STUDY_RECIPE, _parse
    pv360 = SimpleNamespace(header={'owner': 'nmrsu', 'study_operator': 'jkl',
                                    'name_string': 'std_PV360_3.7^^^^', 'id': 'std_PV360_3.7',
                                    'study_name': '94T_protocols', 'study_use_ats': 'Yes'})
    out = _parse(pv360, _STUDY_RECIPE)
    assert out['user_account'] == 'nmrsu' and out['operator'] == 'jkl'
    assert out['subject_name'] == 'std_PV360_3.7^^^^' and out['subject_id'] == 'std_PV360_3.7'
    assert out['use_ats'] == 'Yes'
    # PV5.1/PV6 spell the operator SUBJECT_referral
    pv6 = SimpleNamespace(header={'owner': 'galdan', 'referral': 'galdan'})
    assert _parse(pv6, _STUDY_RECIPE)['operator'] == 'galdan'
    assert 'name' not in out and 'id' not in out and 'type' not in out
