def amwg_table(adf):

    """
    Main function goes through series of steps:
    - load the variable data
    - Determine whether there are spatial dims; if yes, do global average (TODO: regional option)
    - Apply annual average (TODO: add seasonal here)
    - calculates the statistics
      + mean
      + sample size
      + standard deviation
      + standard error of the mean
      + 5/95% confidence interval of the mean
      + linear trend
      + p-value of linear trend
    - puts statistics into a CSV file
    - generates simple HTML that can display the data

    Description of needed inputs from ADF:

    case_names      -> Name(s) of CAM case provided by "cam_case_name"
    input_ts_locs   -> Location(s) of CAM time series files provided by "cam_ts_loc"
    output_loc      -> Location to write AMWG table files to, provided by "cam_diag_plot_loc"
    write_html      -> Logical for whether HTML code is generated to display the table.
    var_list        -> List of CAM output variables provided by "diag_var_list"

    and if doing a CAM baseline comparison:

    baseline_name     -> Name of CAM baseline case provided by "cam_case_name"
    input_ts_baseline -> Location of CAM baseline time series files provied by "cam_ts_loc"

    """

    #Import necessary modules:
    import numpy as np
    import xarray as xr
    from pathlib import Path
    from adf_base import AdfError
    import warnings  # use to warn user about missing files.

    #Import "special" modules:
    try:
        import pandas as pd
    except ImportError:
        print("Pandas module does not exist in python path, but is needed for amwg_table.")
        print("Please install module, e.g. 'pip install pandas'.")
        sys.exit(1)

    try:
        import scipy.stats as stats # for easy linear regression and testing
    except ImportError:
        print("Scipy module does not exist in python path, but is needed for amwg_table.")
        print("Please install module, e.g. 'pip install scipy'.")


    #Additional information:
    #----------------------

    # GOAL: replace the "Tables" set in AMWG
    #       Set Description
    #   1 Tables of ANN, DJF, JJA, global and regional means and RMSE.
    #
    # STRATEGY:
    # I think the right solution is to generate one CSV (or other?) file that
    # contains all of the data.
    # So we need:
    # - a function that would produces the data, and
    # - then call a function that adds the data to a file
    # - another function(module?) that uses the file to produce a "web page"

    # IMPLEMENTATION:
    # - assume that we will have time series of global averages already ... that should be done ahead of time
    # - given a variable or file for a variable (equivalent), we will calculate the all-time, DJF, JJA, MAM, SON
    #   + mean
    #   + standard error of the mean
    #     -- 95% confidence interval for the mean, estimated by:
    #     ---- CI95 = mean + (SE * 1.96)
    #     ---- CI05 = mean - (SE * 1.96)
    #   + standard deviation
    # AMWG also includes the RMSE b/c it is comparing two things, but I will put that off for now.

    # DETAIL: we use python's type hinting as much as possible

    # in future, provide option to do multiple domains
    # They use 4 pre-defined domains:
    domains = {"global": (0, 360, -90, 90),
               "tropics": (0, 360, -20, 20),
               "southern": (0, 360, -90, -20),
               "northern": (0, 360, 20, 90)}

    # and then in time it is DJF JJA ANN

    # within each domain and season
    # the result is just a table of
    # VARIABLE-NAME, RUN VALUE, OBS VALUE, RUN-OBS, RMSE
    #----------------------

    #Notify user that script has started:
    print("  Calculating AMWG variable table...")


    #Extract needed quantities from ADF object:
    #-----------------------------------------
    write_html = adf.get_basic_info("create_html")
    var_list   = adf.diag_var_list

    #Special ADF variable which contains the output path for
    #all generated plots and tables:
    output_loc = adf.plot_location

    #CAM simulation variables (must be lists):
    case_names    = [adf.get_cam_info("cam_case_name", required=True)]
    input_ts_locs = [adf.get_cam_info("cam_ts_loc", required=True)]

    #Check if a baseline simulation is also being used:
    if not adf.get_basic_info("compare_obs"):
        #Extract CAM baseline variaables:
        baseline_name     = adf.get_baseline_info("cam_case_name", required=True)
        input_ts_baseline = adf.get_baseline_info("cam_ts_loc", required=True)

        #Append to case list:
        case_names.append(baseline_name)
        input_ts_locs.append(input_ts_baseline)
    #-----------------------------------------

    #Convert output location string to a Path object:
    output_location = Path(output_loc)

    #Loop over CAM cases:
    for case_idx, case_name in enumerate(case_names):

        #Generate input file path:
        input_location = Path(input_ts_locs[case_idx])

        #Check that time series input directory actually exists:
        if not input_location.is_dir():
            errmsg = "Time series directory '{}' not found.  Script is exiting.".format(input_ts_loc)
            raise AdfError(errmsg)
        #Write to debug log if enabled:
        adf.debug_log(f"DEBUG: location of files is {str(input_location)}")
        #Check if analysis directory exists, and if not, then create it:
        if not output_location.is_dir():
            print("    {} not found, making new directory".format(output_loc))
            output_location.mkdir(parents=True)

        #Create output file name:
        output_csv_file = output_location / "amwg_table_{}.csv".format(case_name)

        #Create HTML output file name as well, if needed:
        if write_html:
            output_html_file = output_location / "amwg_table_{}.html".format(case_name)

        #Given that this is a final, user-facing analysis, go ahead and re-do it every time:
        if Path(output_csv_file).is_file():
            Path.unlink(output_csv_file)

        if write_html:
            if Path(output_html_file).is_file():
                Path.unlink(output_html_file)

        #Loop over CAM output variables:
        for var in var_list:

            #Notify users of variable being added to table:
            print("\t \u25B6 Variable '{}' being added to table".format(var))

            #Create list of time series files present for variable:
            ts_filenames = '{}.*.{}.*nc'.format(case_name, var)
            ts_files = sorted(list(input_location.glob(ts_filenames)))

            # If no files exist, try to move to next variable. --> Means we can not proceed with this variable, and it'll be problematic later.
            if not ts_files:
                errmsg = "Time series files for variable '{}' not found.  Script will continue to next variable.".format(var)
                #  end_diag_script(errmsg) # Previously we would kill the run here.
                warnings.warn(errmsg)
                continue

            #TEMPORARY:  For now, make sure only one file exists:
            if len(ts_files) != 1:
                errmsg =  "Currently the AMWG table script can only handle one time series file per variable."
                errmsg += " Multiple files were found for the variable '{}'".format(var)
                raise AdfError(errmsg)

            #Load model data from file:
            data = _load_data(ts_files[0], var)

            #Extract units string, if available:
            if hasattr(data, 'units'):
                unit_str = data.units
            else:
                unit_str = '--'

            #Check if variable has a vertical coordinate:
            if 'lev' in data.coords or 'ilev' in data.coords:
                print("Variable '{}' has a vertical dimension, ".format(var)+\
                      "which is currently not supported for the AMWG Table. Skipping...")
                #Skip this variable and move to the next variable in var_list:
                continue

            # we should check if we need to do area averaging:
            if len(data.dims) > 1:
                # flags that we have spatial dimensions
                # Note: that could be 'lev' which should trigger different behavior
                # Note: we should be able to handle (lat, lon) or (ncol,) cases, at least
                data = _spatial_average(data)  # changes data "in place"

            # In order to get correct statistics, average to annual or seasonal
            data = data.groupby('time.year').mean(dim='time') # this should be fast b/c time series should be in memory
                                                              # NOTE: data will now have a 'year' dimension instead of 'time'
            # Now that data is (time,), we can do our simple stats:
            data_mean = data.mean()
            data_sample = len(data)
            data_std = data.std()
            data_sem = data_std / data_sample
            data_ci = data_sem * 1.96  # https://en.wikipedia.org/wiki/Standard_error
            data_trend = stats.linregress(data.year, data.values)
            # These get written to our output file:
            # create a dataframe:
            cols = ['variable', 'unit', 'mean', 'sample size', 'standard dev.',
                    'standard error', '95% CI', 'trend', 'trend p-value']
            row_values = [var, unit_str, data_mean.data.item(), data_sample,
                          data_std.data.item(), data_sem.data.item(), data_ci.data.item(),
                          f'{data_trend.intercept : 0.3f} + {data_trend.slope : 0.3f} t',
                          data_trend.pvalue]

            # Format entries:
            dfentries = {c:[row_values[i]] for i,c in enumerate(cols)}

            # Add entries to Pandas structure:
            df = pd.DataFrame(dfentries)

            # Check if the output CSV file exists,
            # if so, then append to it:
            if output_csv_file.is_file():
                df.to_csv(output_csv_file, mode='a', header=False, index=False)
            else:
                df.to_csv(output_csv_file, header=cols, index=False)

            # last step is to write the html file; overwrites previous version since we're supposed to be adding to it
            if write_html:
                _write_html(output_csv_file, output_html_file)

        #End of var_list loop
        #--------------------

    #End of model case loop
    #----------------------

    #Notify user that script has ended:
    print("...AMWG variable table has been generated successfully.")

##################
# Helper functions
##################

def _load_data(dataloc, varname):
    import xarray as xr
    ds = xr.open_dataset(dataloc)
    return ds[varname]

#####

def _spatial_average(indata):
    import xarray as xr
    import numpy as np
    assert 'lev' not in indata.coords
    assert 'ilev' not in indata.coords
    if 'lat' in indata.coords:
        weights = np.cos(np.deg2rad(indata.lat))
        weights.name = "weights"
    elif 'ncol' in indata.coords:
        print("WARNING: We need a way to get area variable. Using equal weights.")
        weights = xr.DataArray(1.)
        weights.name = "weights"
    else:
        weights = xr.DataArray(1.)
        weights.name = "weights"
    weighted = indata.weighted(weights)
    # we want to average over all non-time dimensions
    avgdims = [dim for dim in indata.dims if dim != 'time']
    return weighted.mean(dim=avgdims)

#####

def _write_html(f, out):
    import pandas as pd
    df = pd.read_csv(f)
    html = df.to_html(index=False, border=1, justify='center', float_format='{:,.3g}'.format)  # should return string
    preamble = f"""<html><head></head><body><h1>{f.stem}<h1>"""
    ending = """</body></html>"""
    with open(out, 'w') as hfil:
        hfil.write(preamble)
        hfil.write(html)
        hfil.write(ending)

##############
#END OF SCRIPT
